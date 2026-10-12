from __future__ import annotations

import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from challenge32.collection import CollectionError, CollectionPaths, build_database, initialize_collection
from challenge32.collection_filing import file_section, plan_filing
from challenge32.collection_metadata import metadata_from_details
from challenge32.collection import CardKey


def fixture(root: Path) -> CollectionPaths:
    deck = root / "decks" / "naya" / "sample"
    deck.mkdir(parents=True)
    (deck / "deck.toml").write_text(
        'slug = "sample"\ndisplay_name = "Sample"\nsource = "archidekt"\n'
        'url = "https://archidekt.com/decks/1/sample"\ncolor_identity = "naya"\n',
        encoding="utf-8",
    )
    (deck / "current.txt").write_text("# Format: 2\n1 Sol Ring (cmm) 396\n", encoding="utf-8")
    paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
    with contextlib.redirect_stdout(io.StringIO()):
        initialize_collection(paths)
    paths.holdings.write_text(
        "card,printing,foil,quantity,category,rarity,colour_identity,type_line,notes\n"
        "Sol Ring,cmm:396,no,1,regular,uncommon,C,Artifact,\n"
        "White Rare,tst:1,no,2,regular,rare,W,Creature,\n"
        "White Uncommon,tst:2,yes,1,regular,uncommon,W,Creature,\n"
        "Blue Rare,tst:3,no,1,regular,mythic,U,Creature,\n"
        "Dual Land,tst:4,no,1,regular,rare,WU,Land — Plains Island,\n", encoding="utf-8",
    )
    imported = paths.locations / "staging" / "imported" / "batch.csv"
    imported.parent.mkdir()
    imported.write_text(
        "card,printing,foil,quantity,notes\n"
        "White Rare,tst:1,no,2,\n"
        "White Uncommon,tst:2,yes,1,\n"
        "Blue Rare,tst:3,no,1,\n"
        "Dual Land,tst:4,no,1,\n", encoding="utf-8",
    )
    build_database(paths)
    return paths


class CollectionFilingTests(unittest.TestCase):
    def test_preview_and_confirm_moves_only_selected_section(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = fixture(Path(temporary))
            imported = paths.locations / "staging" / "imported" / "batch.csv"
            before = imported.read_bytes()
            holdings = paths.holdings.read_bytes()
            self.assertEqual(plan_filing(paths, "white").copies, 3)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(file_section(paths, "white", preview=True))
            self.assertEqual(imported.read_bytes(), before)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(file_section(paths, "white", confirm=lambda _: "yes"))
            self.assertEqual(paths.holdings.read_bytes(), holdings)
            self.assertNotIn(b"White Rare", imported.read_bytes())
            self.assertIn(b"Blue Rare", imported.read_bytes())
            self.assertIn(b"Dual Land", imported.read_bytes())
            self.assertIn(b"White Rare,tst:1,no,2", (paths.locations / "binders" / "white.csv").read_bytes())
            self.assertIn(b"White Uncommon,tst:2,yes,1", (paths.locations / "reserve.csv").read_bytes())
            self.assertEqual(plan_filing(paths, "white").copies, 0)
            self.assertEqual(plan_filing(paths, "lands").copies, 1)
            with sqlite3.connect(paths.database) as connection:
                counts = dict(connection.execute(
                    "SELECT locations.name, SUM(placements.quantity) FROM placements "
                    "JOIN locations ON locations.id = placements.location_id "
                    "WHERE locations.kind != 'deck' GROUP BY locations.name"
                ))
            self.assertEqual(counts, {"binder:white": 2, "reserve": 1, "staging": 2})

    def test_cancel_and_missing_colour_do_not_move_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = fixture(Path(temporary))
            imported = paths.locations / "staging" / "imported" / "batch.csv"
            before = imported.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(file_section(paths, "white", confirm=lambda _: "no"))
            self.assertEqual(imported.read_bytes(), before)
            paths.holdings.write_text(
                paths.holdings.read_text(encoding="utf-8").replace(",rare,W,Creature,", ",rare,,Creature,"),
                encoding="utf-8",
            )
            build_database(paths)
            with self.assertRaisesRegex(CollectionError, "without colour data"):
                plan_filing(paths, "white")
            self.assertEqual(imported.read_bytes(), before)

    def test_exact_printing_metadata_includes_colourless_and_card_type(self) -> None:
        card = CardKey("Dual Land", "tst:4", "no")
        metadata = metadata_from_details(card, {
            "name": "Dual Land", "rarity": "rare", "color_identity": ["U", "W"],
            "type_line": "Land — Plains Island",
        })
        self.assertEqual(metadata.colour_identity, "WU")
        self.assertEqual(metadata.type_line, "Land — Plains Island")
        colourless = metadata_from_details(CardKey("Sol Ring", "cmm:396"), {
            "name": "Sol Ring", "rarity": "uncommon", "color_identity": [], "type_line": "Artifact",
        })
        self.assertEqual(colourless.colour_identity, "C")


if __name__ == "__main__":
    unittest.main()
