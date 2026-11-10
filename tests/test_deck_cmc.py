from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from challenge32.cli import main
from challenge32.collection import CardKey, CollectionRow, _write_holdings


def write_deck(root: Path, slug: str, name: str, cards: str) -> None:
    directory = root / "decks" / "white" / slug
    directory.mkdir(parents=True)
    (directory / "deck.toml").write_text(
        f'slug = "{slug}"\ndisplay_name = "{name}"\nsource = "archidekt"\n'
        f'url = "https://archidekt.com/decks/1/{slug}"\ncolor_identity = "white"\n',
        encoding="utf-8",
    )
    (directory / "current.txt").write_text("# Format: 2\n" + cards, encoding="utf-8")


class DeckCmcTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.holdings = self.root / "collection" / "holdings.csv"

    def run_cmc(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["cmc", "--decks", str(self.root / "decks"),
                           "--collection", str(self.root / "collection")])
        return status, output.getvalue()

    def test_totals_include_commander_quantities_and_front_spells(self) -> None:
        write_deck(self.root, "higher", "Higher", """
// Commander
1 Commander (tst) 1
// Creature
2 Spell (tst) 2
1 Dowsing Dagger // Lost Vale (tst) 3
// Land
1 Odd Land (tst) 4
""")
        write_deck(self.root, "lower", "Lower", "// Land\n1 Odd Land (tst) 4\n")
        _write_holdings(self.holdings, [
            CollectionRow(CardKey("Commander", "tst:1", "no"), 1,
                          type_line="Legendary Creature", mana_cost="{3}{W}", mana_value=4),
            CollectionRow(CardKey("Spell", "tst:2", "no"), 2,
                          type_line="Creature", mana_cost="{2}{W}", mana_value=3),
            CollectionRow(CardKey("Dowsing Dagger // Lost Vale", "tst:3", "no"), 1,
                          type_line="Artifact — Equipment // Land", mana_cost="{2} // ", mana_value=2),
            CollectionRow(CardKey("Odd Land", "tst:4", "no"), 1,
                          type_line="Legendary Land", mana_cost="", mana_value=5),
        ])
        status, output = self.run_cmc()
        self.assertEqual(status, 0)
        self.assertEqual(output.splitlines(), [
            "Total CMC  Deck",
            "        0  Lower",
            "       12  Higher",
        ])

    def test_missing_mana_value_is_an_error_not_a_partial_total(self) -> None:
        write_deck(self.root, "missing", "Missing", "1 Unknown Card (tst) 1\n")
        _write_holdings(self.holdings, [
            CollectionRow(CardKey("Unknown Card", "tst:1", "no"), 1, type_line="Creature"),
        ])
        status, output = self.run_cmc()
        self.assertEqual(status, 1)
        self.assertIn("Missing owned printing or mana value", output)
        self.assertNotIn("Total CMC", output)


if __name__ == "__main__":
    unittest.main()
