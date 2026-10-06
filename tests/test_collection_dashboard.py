from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from challenge32.collection import CollectionPaths, initialize_collection
from challenge32.collection_dashboard import build_collection_dashboard


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


class CollectionDashboardTests(unittest.TestCase):
    def test_dashboard_rebuilds_database_and_writes_searchable_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(
                root,
                "omnislash",
                "Omnislash",
                "// Artifact\n1 Sol Ring (cmm) 396 #artifact\n",
            )
            paths = CollectionPaths(
                root=root / "collection",
                decks=root / "decks",
                database=root / "data" / "collection.sqlite",
            )
            initialize_collection(paths)
            (paths.root / "locations" / "reserve.csv").write_text(
                "card,printing,foil,quantity,notes\nSol Ring,cmm:396,unknown,1,\n",
                encoding="utf-8",
            )
            output = root / "data" / "collection-dashboard"
            with patch(
                "challenge32.collection_dashboard.load_set_names",
                return_value={"cmm": "Commander Masters"},
            ):
                payload = build_collection_dashboard(paths, output)
            self.assertEqual(payload["summary"]["conflicts"], 1)
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "assets" / "app.js").exists())
            self.assertTrue((output / "assets" / "style.css").exists())
            self.assertTrue((output / "data.json").exists())
            saved = json.loads((output / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["inventory"][0]["status"], "conflict")
            self.assertEqual(saved["inventory"][0]["set_name"], "Commander Masters")
            self.assertEqual(saved["inventory"][0]["card_number"], "396")
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(
                    connection.execute("SELECT name FROM set_names WHERE code = 'cmm'").fetchone()[0],
                    "Commander Masters",
                )


if __name__ == "__main__":
    unittest.main()
