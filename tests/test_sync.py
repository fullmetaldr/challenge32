from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from mtg_parser.card import Card

from challenge32.archidekt import ArchidektClient
from challenge32.cli import slugify
from challenge32.colors import identity_name
from challenge32.dashboard import build_dashboard
from challenge32.models import DeckConfig
from challenge32.progress import update_progress_table
from challenge32.sync import deck_hash, render_body, synchronize


class SyncTests(unittest.TestCase):
    def test_identity_and_slug_helpers(self) -> None:
        self.assertEqual(identity_name(["White", "Red", "Green"]), "naya")
        self.assertEqual(identity_name(["White", "Red"]), "boros")
        self.assertEqual(identity_name(["White", "Green"]), "selesnya")
        self.assertEqual(identity_name(["Blue", "Green"]), "simic")
        self.assertEqual(identity_name([]), "colorless")
        self.assertEqual(slugify("Cloud, Midgar Mercenary"), "cloud-midgar-mercenary")

    def test_archidekt_payload_transform(self) -> None:
        payload = ArchidektClient._as_mtg_parser_payload(
            {
                "categories": {"Commander": {"name": "Commander", "includedInDeck": True}},
                "cardMap": {
                    "one": {
                        "name": "Cloud, Ex-SOLDIER",
                        "qty": 1,
                        "setCode": "fic",
                        "collectorNumber": "202",
                        "categories": ["Commander"],
                    }
                },
            }
        )
        self.assertEqual(payload["categories"][0]["name"], "Commander")
        self.assertEqual(payload["cards"][0]["card"]["oracleCard"]["name"], "Cloud, Ex-SOLDIER")

    def test_render_is_deterministic_and_keeps_tags(self) -> None:
        cards = [
            Card("Sol Ring", 1, "cmm", "396", ["Artifact", "Ramp"]),
            Card("Cloud, Ex-SOLDIER", 1, "fic", "202", ["Commander"]),
        ]
        body = render_body(cards)
        self.assertIn("// Commander", body)
        self.assertIn("1 Cloud, Ex-SOLDIER (fic) 202 #commander", body)
        self.assertEqual(deck_hash(body), deck_hash(body))

    def test_sync_creates_snapshot_and_does_not_duplicate_unchanged_deck(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "decks" / "naya" / "omnislash"
            config = DeckConfig(
                directory=directory,
                slug="omnislash",
                display_name="Omnislash",
                source="archidekt",
                url="https://archidekt.com/decks/15661283/omnislash",
                color_identity="naya",
            )
            cards = [Card("Cloud, Ex-SOLDIER", 1, "fic", "202", ["Commander"])]
            retrieved_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
            first = synchronize(config, cards, retrieved_at=retrieved_at)
            second = synchronize(config, cards, retrieved_at=retrieved_at)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(len(list((directory / "versions").glob("*.txt"))), 1)
            state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["current_version"], first["version"])
            self.assertTrue((directory / "notes" / "status.md").exists())

    def test_progress_refresh_reads_existing_decks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decks_root = root / "decks"
            directory = decks_root / "jeskai" / "walk-this-plane"
            directory.mkdir(parents=True)
            (directory / "deck.toml").write_text(
                '\n'.join(
                    [
                        'slug = "walk-this-plane"',
                        'display_name = "Walk this plane!"',
                        'source = "archidekt"',
                        'url = "https://archidekt.com/decks/1/walk_this_plane"',
                        'color_identity = "jeskai"',
                        '',
                    ]
                ),
                encoding="utf-8",
            )
            (directory / "current.txt").write_text(
                "// Commander\n1 Commodore Guff #commander\n", encoding="utf-8"
            )
            readme = root / "README.md"
            readme.write_text(
                "# Challenge32\n\n## Challenge progress\n\nold table\n\n## Current synchronizer\n",
                encoding="utf-8",
            )
            count = update_progress_table(readme, decks_root)
            updated = readme.read_text(encoding="utf-8")
            self.assertEqual(count, 1)
            self.assertIn("| Jeskai | Tracked | [Walk this plane!]", updated)
            self.assertIn("| Yore-Tiller | Not started |", updated)

    def test_dashboard_builds_data_and_copies_deck_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decks_root = root / "decks"
            directory = decks_root / "jeskai" / "walk-this-plane"
            directory.mkdir(parents=True)
            (directory / "deck.toml").write_text(
                '\n'.join(
                    [
                        'slug = "walk-this-plane"',
                        'display_name = "Walk this plane!"',
                        'source = "archidekt"',
                        'url = "https://archidekt.com/decks/1/walk_this_plane"',
                        'color_identity = "jeskai"',
                        '',
                    ]
                ),
                encoding="utf-8",
            )
            (directory / "current.txt").write_text(
                "// Commander\n1 Commodore Guff #commander\n\n// Artifact\n1 Sol Ring #artifact\n",
                encoding="utf-8",
            )
            output = root / "site"
            count = build_dashboard(decks_root, output)
            data = json.loads((output / "data.json").read_text(encoding="utf-8"))
            jeskai = next(item for item in data["identities"] if item["key"] == "jeskai")
            self.assertEqual(count, 1)
            self.assertEqual(jeskai["decks"][0]["commander"], ["Commodore Guff"])
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "assets" / "app.js").exists())
            self.assertTrue((output / "decks" / "jeskai" / "walk-this-plane" / "current.txt").exists())


if __name__ == "__main__":
    unittest.main()
