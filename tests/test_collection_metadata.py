from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from challenge32.card_catalog import CardCatalogError
from challenge32.collection import CardKey, CollectionError, CollectionPaths, build_database, initialize_collection
from challenge32.collection_metadata import _matches_card_name, metadata_from_details


class CollectionMetadataTests(unittest.TestCase):
    def test_double_faced_name_and_type(self) -> None:
        self.assertTrue(_matches_card_name("Fire // Ice", "Fire // Ice"))
        self.assertTrue(_matches_card_name("Blood Crypt", "Blood Crypt // Blood Crypt"))
        self.assertFalse(_matches_card_name("Blood Crypt", "Blood Crypt // Other Card"))
        details = {
            "name": "Blood Crypt // Blood Crypt", "rarity": "rare", "color_identity": ["R", "B"],
            "card_faces": [{"type_line": "Land — Swamp Mountain"}, {"type_line": "Land — Swamp Mountain"}],
        }
        metadata = metadata_from_details(CardKey("Blood Crypt", "ecl:349"), details)
        self.assertEqual(metadata.type_line, "Land — Swamp Mountain // Land — Swamp Mountain")
        self.assertEqual(metadata.colour_identity, "BR")

    def test_mismatched_name_is_not_accepted(self) -> None:
        with self.assertRaises(CardCatalogError):
            metadata_from_details(CardKey("Sol Ring", "cmm:396"), {
                "name": "Another Card", "rarity": "rare", "color_identity": [], "type_line": "Artifact",
            })

    def test_holdings_metadata_is_derived_into_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deck = root / "decks" / "naya" / "sample"
            deck.mkdir(parents=True)
            (deck / "deck.toml").write_text(
                'slug = "sample"\ndisplay_name = "Sample"\nsource = "archidekt"\n'
                'url = "https://archidekt.com/decks/1/sample"\ncolor_identity = "naya"\n', encoding="utf-8",
            )
            (deck / "current.txt").write_text("1 Sol Ring (cmm) 396\n", encoding="utf-8")
            paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
            initialize_collection(paths)
            paths.holdings.write_text(
                "card,printing,foil,quantity,category,rarity,colour_identity,type_line,notes\n"
                "Sol Ring,cmm:396,unknown,1,,uncommon,C,Artifact,\n", encoding="utf-8",
            )
            build_database(paths)
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(
                    connection.execute("SELECT rarity, colour_identity, type_line FROM cards").fetchone(),
                    ("uncommon", "C", "Artifact"),
                )
            paths.holdings.write_text(
                "card,printing,foil,quantity,category,rarity,colour_identity,type_line,notes\n"
                "Sol Ring,cmm:396,unknown,1,,uncommon,WU,Artifact,\n", encoding="utf-8",
            )
            build_database(paths)
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(connection.execute("SELECT colour_identity FROM cards").fetchone()[0], "WU")
            paths.holdings.write_text(
                "card,printing,foil,quantity,category,rarity,colour_identity,type_line,notes\n"
                "Sol Ring,cmm:396,unknown,1,,uncommon,WUW,Artifact,\n", encoding="utf-8",
            )
            with self.assertRaises(CollectionError):
                build_database(paths)


if __name__ == "__main__":
    unittest.main()
