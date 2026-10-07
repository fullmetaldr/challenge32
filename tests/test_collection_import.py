from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from challenge32.collection import CollectionError, CollectionPaths, collection_status, initialize_collection
from challenge32.cli import main
import challenge32.collection_import as importer
from challenge32.collection_import import ingest_batch, select_import_file, undo_batch


def setup_collection(root: Path) -> tuple[CollectionPaths, Path]:
    deck = root / "decks" / "naya" / "sample"
    deck.mkdir(parents=True)
    (deck / "deck.toml").write_text(
        'slug = "sample"\ndisplay_name = "Sample"\nsource = "archidekt"\n'
        'url = "https://archidekt.com/decks/1/sample"\ncolor_identity = "naya"\n',
        encoding="utf-8",
    )
    (deck / "current.txt").write_text(
        "# Format: 2\n// Artifact\n1 Sol Ring (cmm) 396\n", encoding="utf-8"
    )
    paths = CollectionPaths(root=root / "collection", decks=root / "decks", database=root / "data" / "collection.sqlite")
    initialize_collection(paths)
    import_dir = root / "data" / "imports"
    import_dir.mkdir()
    return paths, import_dir


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class CollectionImportTests(unittest.TestCase):
    def test_preview_apply_duplicate_guard_and_undo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, import_dir = setup_collection(Path(temporary))
            source = import_dir / "prerelease.csv"
            source.write_text(
                "Name,Set code,Card number,Foil,Quantity,Purchase price\n"
                "Sol Ring,CMM,396,No,2,99.00\n"
                "Test Card,TST,12,Foil,1,12.00\n"
                "Test Card,TST,12,Yes,2,12.00\n"
                "Etched Card,TST,13,Etched,1,5.00\n",
                encoding="utf-8",
            )
            old_holdings = paths.holdings.read_bytes()
            self.assertFalse(ingest_batch(paths, import_dir, preview=True))
            self.assertEqual(paths.holdings.read_bytes(), old_holdings)
            self.assertTrue(source.exists())
            self.assertFalse(ingest_batch(paths, import_dir, confirm=lambda _prompt: ""))
            self.assertTrue(source.exists())
            self.assertTrue(ingest_batch(paths, import_dir, batch="reality-fracture", confirm=lambda _prompt: "yes"))
            self.assertFalse(source.exists())
            self.assertTrue((import_dir / "processed" / "reality-fracture.csv").exists())
            receipt = paths.imports / "batches" / "reality-fracture.csv"
            self.assertTrue(receipt.exists())
            self.assertNotIn("99.00", receipt.read_text(encoding="utf-8"))
            holdings = {row["card"]: row for row in rows(paths.holdings)}
            self.assertEqual(holdings["Sol Ring"]["quantity"], "3")
            self.assertEqual(holdings["Test Card"]["quantity"], "3")
            self.assertEqual(holdings["Etched Card"]["foil"], "yes")
            self.assertEqual(collection_status(paths)["non_deck_placed"], 6)
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(
                    connection.execute("SELECT kind FROM locations WHERE name = 'intake:reality-fracture'").fetchone()[0],
                    "intake",
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT SUM(p.quantity) FROM placements AS p "
                        "JOIN locations AS l ON l.id = p.location_id "
                        "WHERE l.name = 'intake:reality-fracture'"
                    ).fetchone()[0],
                    6,
                )
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            duplicate = import_dir / "same-cards-renamed.csv"
            duplicate.write_text(
                "Card Name,Set Code,Collector Number,Foil?,Quantity,Purchase price\n"
                "Test Card,TST,12,Yes,3,999.00\n"
                "Etched Card,TST,13,Etched,1,1.00\n"
                "Sol Ring,CMM,396,No,2,1.00\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CollectionError, "possible duplicate"):
                ingest_batch(paths, import_dir, preview=True)
            duplicate.unlink()
            self.assertTrue(undo_batch(paths, import_dir, "reality-fracture", confirm=lambda _prompt: "yes"))
            self.assertEqual(paths.holdings.read_bytes(), old_holdings.replace(b"\r\n", b"\n"))
            self.assertFalse((paths.locations / "intake" / "reality-fracture.csv").exists())
            self.assertEqual(rows(paths.imports / "log.csv")[0]["status"], "undone")
            self.assertEqual(collection_status(paths)["conflicts"], 0)

    def test_undo_refuses_changed_intake_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, import_dir = setup_collection(Path(temporary))
            (import_dir / "new.csv").write_text(
                "Card Name,Set Code,Collector Number,Foil?,Quantity\nOther Card,TST,1,No,1\n",
                encoding="utf-8",
            )
            ingest_batch(paths, import_dir, batch="new", confirm=lambda _prompt: "yes")
            intake = paths.locations / "intake" / "new.csv"
            intake.write_text(intake.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            holdings = paths.holdings.read_bytes()
            with self.assertRaisesRegex(CollectionError, "Intake placement changed"):
                undo_batch(paths, import_dir, "new", preview=True)
            self.assertEqual(paths.holdings.read_bytes(), holdings)

    def test_invalid_row_and_multiple_files_do_not_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, import_dir = setup_collection(Path(temporary))
            first = import_dir / "first.csv"
            first.write_text("Name,Set code,Card number,Foil,Quantity\nA,TST,1,No,1\n", encoding="utf-8")
            second = import_dir / "second.csv"
            second.write_text("Name,Set code,Card number,Foil,Quantity\nB,TST,2,,1\n", encoding="utf-8")
            with self.assertRaisesRegex(CollectionError, "Multiple CSV"):
                ingest_batch(paths, import_dir, preview=True)
            self.assertEqual(select_import_file(import_dir, None, confirm=lambda _prompt: "1"), first.resolve())
            with self.assertRaisesRegex(CollectionError, "unrecognised foil"):
                ingest_batch(paths, import_dir, selected=second, preview=True)
            self.assertEqual(len(rows(paths.holdings)), 1)
            self.assertFalse((paths.imports / "log.csv").exists())

    def test_existing_printing_with_different_name_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, import_dir = setup_collection(Path(temporary))
            (import_dir / "wrong-name.csv").write_text(
                "Name,Set code,Card number,Foil,Quantity\nNot Sol Ring,CMM,396,No,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CollectionError, "scanner name"):
                ingest_batch(paths, import_dir, preview=True)
            self.assertFalse((paths.imports / "log.csv").exists())

    def test_cli_preview_discovers_pending_file_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, import_dir = setup_collection(Path(temporary))
            source = import_dir / "pending.csv"
            source.write_text(
                "Name,Set code,Card number,Foil,Quantity\nOther Card,TST,1,No,1\n",
                encoding="utf-8",
            )
            self.assertEqual(main([
                "collection", "ingest", "--preview", "--root", str(paths.root),
                "--decks", str(paths.decks), "--database", str(paths.database),
                "--imports", str(import_dir),
            ]), 0)
            self.assertTrue(source.exists())
            self.assertFalse((paths.imports / "log.csv").exists())

    def test_database_failure_restores_all_source_files_and_pending_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, import_dir = setup_collection(Path(temporary))
            source = import_dir / "failure.csv"
            source.write_text(
                "Name,Set code,Card number,Foil,Quantity\nOther Card,TST,1,No,1\n",
                encoding="utf-8",
            )
            previous_holdings = paths.holdings.read_bytes()
            real_build = importer.build_database
            calls = 0

            def fail_once(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("simulated database failure")
                return real_build(*args, **kwargs)

            with patch.object(importer, "build_database", side_effect=fail_once):
                with self.assertRaisesRegex(RuntimeError, "simulated database failure"):
                    ingest_batch(paths, import_dir, batch="failure", confirm=lambda _prompt: "yes")
            self.assertTrue(source.exists())
            self.assertEqual(paths.holdings.read_bytes(), previous_holdings)
            self.assertFalse((paths.locations / "intake" / "failure.csv").exists())
            self.assertFalse((paths.imports / "log.csv").exists())
            self.assertFalse((import_dir / "processed" / "failure.csv").exists())
            self.assertFalse((paths.database.parent / "collection-import-transaction").exists())
            self.assertEqual(collection_status(paths)["conflicts"], 0)

    def test_interrupted_transaction_blocks_a_second_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, import_dir = setup_collection(Path(temporary))
            (import_dir / "new.csv").write_text(
                "Name,Set code,Card number,Foil,Quantity\nOther Card,TST,1,No,1\n",
                encoding="utf-8",
            )
            (paths.database.parent / "collection-import-transaction").mkdir()
            with self.assertRaisesRegex(CollectionError, "interrupted collection import"):
                ingest_batch(paths, import_dir, preview=True)


if __name__ == "__main__":
    unittest.main()
