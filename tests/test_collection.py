from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from challenge32.collection import (
    CollectionPaths,
    CollectionError,
    collection_status,
    initialize_collection,
)


def write_deck(root: Path, slug: str, display_name: str, body: str) -> None:
    directory = root / "decks" / "naya" / slug
    directory.mkdir(parents=True)
    (directory / "deck.toml").write_text(
        "\n".join(
            [
                f'slug = "{slug}"',
                f'display_name = "{display_name}"',
                'source = "archidekt"',
                f'url = "https://archidekt.com/decks/1/{slug}"',
                'color_identity = "naya"',
                '',
            ]
        ),
        encoding="utf-8",
    )
    (directory / "current.txt").write_text(body, encoding="utf-8")


class CollectionTests(unittest.TestCase):
    def test_init_creates_schema_locations_holdings_and_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(
                root,
                "omnislash",
                "Omnislash",
                "// Commander\n1 Cloud, Ex-SOLDIER (fic) 202 #commander\n\n"
                "// Artifact\n2 Sol Ring (cmm) 396 #artifact\n",
            )
            paths = CollectionPaths(
                root=root / "collection",
                decks=root / "decks",
                database=root / "data" / "collection.sqlite",
            )
            result = initialize_collection(paths)
            self.assertEqual(result["decks"], 1)
            self.assertEqual(result["card_versions"], 2)
            self.assertEqual(result["cards"], 3)
            self.assertTrue((paths.root / "schema.md").exists())
            self.assertTrue((paths.root / "locations" / "maybe" / "omnislash.csv").exists())

            with (paths.root / "holdings.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["printing"], "fic:202")
            self.assertEqual(rows[0]["foil"], "unknown")
            self.assertEqual(rows[1]["card"], "Sol Ring")
            self.assertEqual(rows[1]["quantity"], "2")

            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM placements").fetchone()[0], 2)

    def test_init_requires_both_confirmations_when_confirmation_is_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "omnislash", "Omnislash", "1 Sol Ring (cmm) 396 #artifact\n")
            paths = CollectionPaths(root=root / "collection", decks=root / "decks", database=root / "db.sqlite")
            answers = iter(["yes", "wrong"])
            with self.assertRaises(CollectionError):
                initialize_collection(paths, confirm=lambda _prompt: next(answers))
            self.assertFalse(paths.root.exists())

    def test_new_deck_format_imports_foil_and_normal_without_changing_legacy_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(
                root, "omnislash", "Omnislash",
                "# Format: 2\n// Commander\n1 Cloud, Ex-SOLDIER (fic) 202\n\n"
                "// Creature\n1 Calix, Guided by Fate (mat) 126 *E*\n\n"
                "// Artifact\n1 Sol Ring (cmm) 396 *F*\n",
            )
            paths = CollectionPaths(root=root / "collection", decks=root / "decks", database=root / "db.sqlite")
            initialize_collection(paths)
            with paths.holdings.open(newline="", encoding="utf-8") as handle:
                rows = {row["card"]: row for row in csv.DictReader(handle)}
            self.assertEqual(rows["Cloud, Ex-SOLDIER"]["foil"], "no")
            self.assertEqual(rows["Sol Ring"]["foil"], "yes")
            self.assertEqual(rows["Calix, Guided by Fate"]["foil"], "yes")
            self.assertEqual(rows["Sol Ring"]["printing"], "cmm:396")
            self.assertEqual(collection_status(paths)["conflicts"], 0)

    def test_status_counts_deck_allocation_and_reports_known_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "omnislash", "Omnislash", "1 Sol Ring (cmm) 396 #artifact\n")
            paths = CollectionPaths(root=root / "collection", decks=root / "decks", database=root / "db.sqlite")
            initialize_collection(paths)
            placements = paths.root / "locations" / "reserve.csv"
            placements.write_text(
                "card,printing,foil,quantity,notes\nSol Ring,cmm:396,unknown,1,\n",
                encoding="utf-8",
            )
            result = collection_status(paths)
            self.assertEqual(result["deck_allocated"], 1)
            self.assertEqual(result["non_deck_placed"], 1)
            self.assertEqual(result["conflicts"], 1)


if __name__ == "__main__":
    unittest.main()
