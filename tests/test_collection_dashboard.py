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
    def test_staging_files_are_one_location_in_database_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "omnislash", "Omnislash", "// Artifact\n1 Sol Ring (cmm) 396 #artifact\n")
            paths = CollectionPaths(
                root=root / "collection",
                decks=root / "decks",
                database=root / "data" / "collection.sqlite",
            )
            initialize_collection(paths)
            paths.holdings.write_text(
                "card,printing,foil,quantity,category,notes\nSol Ring,cmm:396,unknown,4,regular,\n",
                encoding="utf-8",
            )
            for relative in ("white.csv", "blue.csv", "imported/batch.csv"):
                source = paths.locations / "staging" / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(
                    "card,printing,foil,quantity,notes\nSol Ring,cmm:396,unknown,1,\n",
                    encoding="utf-8",
                )
            with patch("challenge32.collection_dashboard.load_set_names", return_value={}):
                payload = build_collection_dashboard(paths, root / "data" / "collection-dashboard")
            self.assertEqual(payload["summary"]["non_deck_placed"], 3)
            self.assertEqual(payload["summary"]["different_cards"], 1)
            self.assertEqual(payload["summary"]["known_owned"], 4)
            self.assertEqual(payload["summary"]["in_staging"], 3)
            self.assertEqual(payload["summary"]["in_reserve"], 0)
            self.assertEqual(payload["summary"]["conflicts"], 0)
            self.assertIn(
                {"name": "staging", "kind": "staging", "quantity": 3, "card_versions": 1, "label": "Staging"},
                payload["locations"],
            )
            self.assertIn(
                {"name": "binder:white", "kind": "binder", "quantity": 0, "card_versions": 0, "label": "Binder (White)"},
                payload["locations"],
            )
            self.assertIn(
                {"name": "binder:trade", "kind": "binder", "quantity": 0, "card_versions": 0, "label": "Binder (Trade)"},
                payload["locations"],
            )
            self.assertIn(
                {"name": "binder:sell", "kind": "binder", "quantity": 0, "card_versions": 0, "label": "Binder (Sell)"},
                payload["locations"],
            )
            self.assertEqual(payload["inventory"][0]["locations"], [
                {"name": "staging", "label": "Staging", "quantity": 3},
            ])
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM locations WHERE kind = 'staging'").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(DISTINCT p.source_path) FROM placements AS p "
                        "JOIN locations AS l ON l.id = p.location_id WHERE l.name = 'staging'"
                    ).fetchone()[0],
                    3,
                )

    def test_inventory_counts_names_once_across_printings_and_counts_reserve_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "omnislash", "Omnislash", "// Artifact\n1 Sol Ring (cmm) 396 #artifact\n")
            paths = CollectionPaths(
                root=root / "collection",
                decks=root / "decks",
                database=root / "data" / "collection.sqlite",
            )
            initialize_collection(paths)
            paths.holdings.write_text(
                "card,printing,foil,quantity,category,notes\n"
                "Sol Ring,cmm:396,unknown,1,regular,\n"
                "Sol Ring,2xm:340,no,2,regular,\n",
                encoding="utf-8",
            )
            (paths.locations / "reserve.csv").write_text(
                "card,printing,foil,quantity,notes\nSol Ring,2xm:340,no,2,\n",
                encoding="utf-8",
            )
            output = root / "data" / "collection-dashboard"
            with patch("challenge32.collection_dashboard.load_set_names", return_value={}):
                payload = build_collection_dashboard(paths, output)
            self.assertEqual(payload["summary"]["known_card_versions"], 2)
            self.assertEqual(payload["summary"]["different_cards"], 1)
            self.assertEqual(payload["summary"]["known_owned"], 3)
            self.assertEqual(payload["summary"]["in_staging"], 0)
            self.assertEqual(payload["summary"]["in_reserve"], 2)
            self.assertEqual(payload["summary"]["conflicts"], 0)
            app = (output / "assets" / "app.js").read_text(encoding="utf-8")
            for label in ("Inventory", "No. different cards", "No. total cards", "In Staging", "In Reserve"):
                self.assertIn(label, app)
            self.assertNotIn("Non-deck placements", app)

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
            paths.rarities.write_text(
                "card,printing,rarity\nSol Ring,cmm:396,uncommon\n", encoding="utf-8"
            )
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
            html = (output / "index.html").read_text(encoding="utf-8")
            app = (output / "assets" / "app.js").read_text(encoding="utf-8")
            self.assertEqual(html.count('class="panel-toggle"'), 4)
            for element in ("inventory-pagination", "previous-page", "inventory-page", "next-page"):
                self.assertIn(f'id="{element}"', html)
            self.assertIn("INVENTORY_PAGE_SIZE = 50", app)
            self.assertIn("rows.slice(first, first + INVENTORY_PAGE_SIZE)", app)
            self.assertIn('common: "C", uncommon: "U", rare: "R", mythic: "M"', app)
            self.assertIn('colspan="8"', app)
            self.assertIn('class="inventory-details"', app)
            self.assertIn('aria-expanded="false"', app)
            self.assertIn("locationBreakdown(item)", app)
            saved = json.loads((output / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["inventory"][0]["status"], "conflict")
            self.assertEqual(saved["inventory"][0]["set_name"], "Commander Masters")
            self.assertEqual(saved["inventory"][0]["card_number"], "396")
            self.assertEqual(saved["inventory"][0]["rarity"], "uncommon")
            self.assertIn("<th>Rarity</th>", html)
            self.assertIn("<th>Owned</th>", html)
            self.assertIn("<th>Used</th>", html)
            for old_header in ("<th>Known</th>", "<th>Decks</th>", "<th>Other locations</th>", "<th>Free / unresolved</th>"):
                self.assertNotIn(old_header, html)
            with sqlite3.connect(paths.database) as connection:
                self.assertEqual(
                    connection.execute("SELECT name FROM set_names WHERE code = 'cmm'").fetchone()[0],
                    "Commander Masters",
                )

    def test_expanded_inventory_data_lists_each_deck_and_filed_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_deck(root, "deck-x", "Deck X", "# Format: 2\n1 Sol Ring (cmm) 396\n")
            write_deck(root, "deck-y", "Deck Y", "# Format: 2\n1 Sol Ring (cmm) 396\n")
            paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
            initialize_collection(paths)
            paths.holdings.write_text(
                "card,printing,foil,quantity,category,notes\nSol Ring,cmm:396,no,5,regular,\n",
                encoding="utf-8",
            )
            (paths.locations / "staging" / "white.csv").write_text(
                "card,printing,foil,quantity,notes\nSol Ring,cmm:396,no,1,\n",
                encoding="utf-8",
            )
            (paths.locations / "binders" / "white.csv").write_text(
                "card,printing,foil,quantity,notes\nSol Ring,cmm:396,no,2,\n",
                encoding="utf-8",
            )
            with patch("challenge32.collection_dashboard.load_set_names", return_value={}):
                payload = build_collection_dashboard(paths, root / "data" / "collection-dashboard")
            item = payload["inventory"][0]
            self.assertEqual(item["known_owned"], 5)
            self.assertEqual(item["deck_allocated"], 2)
            self.assertEqual(item["status"], "accounted")
            self.assertEqual(item["decks"], [
                {"name": "Deck X", "quantity": 1}, {"name": "Deck Y", "quantity": 1},
            ])
            self.assertEqual(item["locations"], [
                {"name": "binder:white", "label": "Binder (White)", "quantity": 2},
                {"name": "staging", "label": "Staging", "quantity": 1},
            ])
            self.assertEqual(payload["summary"]["known_owned"], 5)
            self.assertEqual(payload["summary"]["non_deck_placed"], 3)


if __name__ == "__main__":
    unittest.main()
