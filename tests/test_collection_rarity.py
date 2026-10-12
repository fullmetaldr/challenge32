from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

import httpx

from challenge32.collection import CollectionError, CollectionPaths, build_database, initialize_collection
from challenge32.collection_rarity import _matches_card_name, update_rarities


def write_deck(root: Path, body: str) -> None:
    directory = root / "decks" / "naya" / "sample"
    directory.mkdir(parents=True)
    (directory / "deck.toml").write_text(
        'slug = "sample"\ndisplay_name = "Sample"\nsource = "archidekt"\n'
        'url = "https://archidekt.com/decks/1/sample"\ncolor_identity = "naya"\n',
        encoding="utf-8",
    )
    (directory / "current.txt").write_text(body, encoding="utf-8")


class CollectionRarityTests(unittest.TestCase):
    def test_repeated_same_name_faces_match_but_different_faces_do_not(self) -> None:
        self.assertTrue(_matches_card_name("Blood Crypt", "Blood Crypt // Blood Crypt"))
        self.assertFalse(_matches_card_name("Blood Crypt", "Blood Crypt // Other Card"))

    def test_rarity_is_printing_specific_and_unknown_is_not_common(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "# Format: 2\n1 Sol Ring (cmm) 396\n1 Sol Ring (2xm) 340 *F*\n")
            paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
            initialize_collection(paths)
            self.assertEqual(paths.rarities.read_text(encoding="utf-8"), "card,printing,rarity\n")
            paths.rarities.write_text("card,printing,rarity\nSol Ring,cmm:396,uncommon\n", encoding="utf-8")
            build_database(paths)
            with sqlite3.connect(paths.database) as connection:
                rows = connection.execute("SELECT printing, rarity FROM cards ORDER BY printing").fetchall()
            self.assertEqual(rows, [("2xm:340", None), ("cmm:396", "uncommon")])

    def test_enrichment_uses_exact_printing_and_does_not_change_inventory(self) -> None:
        requests: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            return httpx.Response(200, json={
                "name": "Sol Ring", "set": "cmm", "collector_number": "396", "rarity": "uncommon",
            })

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "# Format: 2\n1 Sol Ring (cmm) 396\n")
            paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
            initialize_collection(paths)
            before_holdings = paths.holdings.read_bytes()
            before_staging = (paths.locations / "staging" / "white.csv").read_bytes()
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                result = update_rarities(paths, client=client, progress=lambda _: None, pause=lambda _: None)
                again = update_rarities(paths, client=client, progress=lambda _: None, pause=lambda _: None)
            self.assertEqual(result, {"added": 1, "unresolved": 0, "known": 1, "unavailable": False})
            self.assertEqual(again["added"], 0)
            self.assertEqual(requests, ["/cards/cmm/396"])
            self.assertEqual(paths.holdings.read_bytes(), before_holdings)
            self.assertEqual((paths.locations / "staging" / "white.csv").read_bytes(), before_staging)
            with paths.rarities.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(list(csv.DictReader(handle)), [
                    {"card": "Sol Ring", "printing": "cmm:396", "rarity": "uncommon"},
                ])
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(connection.execute("SELECT rarity FROM cards").fetchone()[0], "uncommon")

    def test_name_mismatch_remains_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "# Format: 2\n1 Sol Ring (cmm) 396\n")
            paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
            initialize_collection(paths)
            def respond(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json={
                    "name": "Another Card", "set": "cmm", "collector_number": "396", "rarity": "rare",
                })
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                result = update_rarities(paths, client=client, progress=lambda _: None, pause=lambda _: None)
            self.assertEqual(result["unresolved"], 1)
            self.assertEqual(paths.rarities.read_text(encoding="utf-8"), "card,printing,rarity\n")

    def test_duplicate_rarity_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "# Format: 2\n1 Sol Ring (cmm) 396\n")
            paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
            initialize_collection(paths)
            paths.rarities.write_text(
                "card,printing,rarity\nSol Ring,cmm:396,rare\nSol Ring,cmm:396,uncommon\n", encoding="utf-8",
            )
            with self.assertRaises(CollectionError):
                build_database(paths)

    def test_unicode_card_name_receives_rarity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "# Format: 2\n1 Éowyn, Shieldmaiden (ltc) 1\n")
            paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
            initialize_collection(paths)
            paths.rarities.write_text(
                "card,printing,rarity\n\"Éowyn, Shieldmaiden\",ltc:1,mythic\n", encoding="utf-8",
            )
            build_database(paths)
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(connection.execute("SELECT rarity FROM cards").fetchone()[0], "mythic")


if __name__ == "__main__":
    unittest.main()
