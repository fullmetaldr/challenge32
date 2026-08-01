from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from mtg_parser.card import Card

from challenge32_sync.archidekt import ArchidektClient
from challenge32_sync.models import DeckConfig
from challenge32_sync.sync import deck_hash, render_body, synchronize


class SyncTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

