from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mtg_parser.card import Card

from challenge32.archidekt import SourcedCard
from challenge32.collection import CollectionPaths, _read_rows, build_database, initialize_collection
from challenge32.collection import CollectionError
from challenge32.collection_metadata import CardMetadata
from challenge32.collection_sync import FetchedDeck, sync_all
from challenge32.models import DeckConfig
from challenge32.sync import synchronize


def card(name: str, printing: str, *, foil: str = "normal") -> Card:
    set_code, number = printing.split(":")
    return SourcedCard(Card(name, 1, set_code, number, ["Instant"]),
                       type_category="Instant", finish=foil)


def metadata(_card, _root) -> CardMetadata:
    return CardMetadata("rare", "W", "Instant")


class CollectionSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.paths = CollectionPaths(root / "collection", root / "decks", root / "data" / "collection.sqlite")
        self.configs: list[DeckConfig] = []

    def setup_decks(self, decks: dict[str, list[Card]]) -> None:
        for slug, cards in decks.items():
            directory = self.paths.decks / "white" / slug
            directory.mkdir(parents=True)
            config = DeckConfig(directory, slug, slug, "archidekt", f"https://archidekt.com/decks/{slug}", "white")
            self.configs.append(config)
            (directory / "deck.toml").write_text(
                f'slug = "{slug}"\ndisplay_name = "{slug}"\nsource = "archidekt"\n'
                f'url = "{config.url}"\ncolor_identity = "white"\n', encoding="utf-8")
            (directory / "current.txt").write_text(
                "# Format: 2\n" + "".join(
                    f"1 {entry.name} ({entry.extension}) {entry.number}"
                    f"{' *F*' if entry.finish == 'foil' else ''}\n" for entry in cards
                ), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            initialize_collection(self.paths)

    def fetched(self, deck_cards: dict[str, list[Card]], maybes: dict[str, list[Card]] | None = None) -> list[FetchedDeck]:
        maybes = maybes or {}
        return [FetchedDeck(config, tuple(deck_cards[config.slug]), tuple(maybes.get(config.slug, [])))
                for config in self.configs]

    def apply(self, fetched: list[FetchedDeck], answers: list[str]) -> None:
        iterator = iter(answers)
        with contextlib.redirect_stdout(io.StringIO()):
            applied = sync_all(self.paths, fetched, confirm=lambda _message: next(iterator),
                               metadata_lookup=metadata)
        self.assertTrue(applied)
        self.assertEqual(list(iterator), [])

    def test_interdeck_transfer_needs_no_new_holding_or_staging(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"first": [ring], "second": [path]})
        before = self.paths.holdings.read_bytes()
        self.apply(self.fetched({"first": [path], "second": [ring]}), ["y"])
        self.assertEqual(self.paths.holdings.read_bytes(), before)
        self.assertFalse((self.paths.locations / "staging" / "deck-sync.csv").exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(sync_all(
                self.paths, self.fetched({"first": [path], "second": [ring]}),
                confirm=lambda _message: self.fail("unchanged sync must not prompt"),
                metadata_lookup=metadata,
            ))

    def test_printing_correction_changes_holding_without_staging(self) -> None:
        old = card("Path to Exile", "cmm:51")
        new = card("Path to Exile", "2xm:25", foil="foil")
        self.setup_decks({"first": [old]})
        self.apply(self.fetched({"first": [new]}), ["c", "y"])
        rows = _read_rows(self.paths.holdings, include_category=True)
        self.assertEqual([(row.card.printing, row.card.foil) for row in rows], [("2xm:25", "yes")])
        self.assertFalse((self.paths.locations / "staging" / "deck-sync.csv").exists())

    def test_physical_replacement_stages_old_and_confirms_new_copy(self) -> None:
        old = card("Path to Exile", "cmm:51")
        new = card("Path to Exile", "2xm:25")
        self.setup_decks({"first": [old]})
        self.apply(self.fetched({"first": [new]}), ["r", "y", "y"])
        holdings = _read_rows(self.paths.holdings, include_category=True)
        self.assertEqual({row.card.printing for row in holdings}, {"cmm:51", "2xm:25"})
        staged = _read_rows(self.paths.locations / "staging" / "deck-sync.csv")
        self.assertEqual([(row.card.printing, row.quantity) for row in staged], [("cmm:51", 1)])

    def test_incoming_card_draws_from_staging(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"first": [ring]})
        with self.paths.holdings.open("a", encoding="utf-8") as handle:
            handle.write("Path to Exile,cmm:51,no,1,,rare,W,Instant,\n")
        staging = self.paths.locations / "staging" / "white.csv"
        staging.write_text("card,printing,foil,quantity,notes\nPath to Exile,cmm:51,no,1,\n", encoding="utf-8")
        build_database(self.paths)
        self.apply(self.fetched({"first": [ring, path]}), ["y"])
        self.assertFalse(_read_rows(staging))
        self.assertEqual(sum(row.quantity for row in _read_rows(self.paths.holdings, include_category=True)), 2)

    def test_multiple_sources_require_choice(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"first": [ring]})
        with self.paths.holdings.open("a", encoding="utf-8") as handle:
            handle.write("Path to Exile,cmm:51,no,2,,rare,W,Instant,\n")
        staging = self.paths.locations / "staging" / "white.csv"
        binder = self.paths.locations / "binders" / "white.csv"
        contents = "card,printing,foil,quantity,notes\nPath to Exile,cmm:51,no,1,\n"
        staging.write_text(contents, encoding="utf-8")
        binder.write_text(contents, encoding="utf-8")
        build_database(self.paths)
        self.apply(self.fetched({"first": [ring, path]}), ["2", "y"])
        self.assertFalse(_read_rows(staging))
        self.assertEqual(_read_rows(binder)[0].quantity, 1)

    def test_maybe_board_removal_goes_to_staging(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"first": [ring]})
        self.apply(self.fetched({"first": [ring]}, {"first": [path]}), ["y", "y"])
        self.assertEqual(_read_rows(self.paths.locations / "maybe" / "first.csv")[0].card.name, "Path to Exile")
        self.apply(self.fetched({"first": [ring]}), ["y"])
        self.assertFalse(_read_rows(self.paths.locations / "maybe" / "first.csv"))
        self.assertEqual(_read_rows(self.paths.locations / "staging" / "deck-sync.csv")[0].card.name, "Path to Exile")

    def test_preview_and_cancel_do_not_write(self) -> None:
        old = card("Path to Exile", "cmm:51")
        new = card("Path to Exile", "2xm:25")
        self.setup_decks({"first": [old]})
        current = self.configs[0].directory / "current.txt"
        before = (current.read_bytes(), self.paths.holdings.read_bytes())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(sync_all(self.paths, self.fetched({"first": [new]}), preview=True))
            self.assertFalse(sync_all(self.paths, self.fetched({"first": [new]}),
                                      confirm=lambda _message: "c" if "correction" in _message else "n",
                                      metadata_lookup=metadata))
        self.assertIn("Deck out: 1 Path to Exile (cmm:51) [no]", output.getvalue())
        self.assertIn("Deck in:  1 Path to Exile (2xm:25) [no]", output.getvalue())
        self.assertIn("  In:  1 Path to Exile (2xm:25) [no]\n\nCollection reconciliation:\n",
                      output.getvalue())
        self.assertEqual((current.read_bytes(), self.paths.holdings.read_bytes()), before)

    def test_preview_lists_only_changed_decks(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"unchanged": [ring], "changed": [ring]})
        for config in self.configs:
            synchronize(config, [ring])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(sync_all(
                self.paths,
                self.fetched({"unchanged": [ring], "changed": [ring, path]}),
                preview=True,
            ))
        self.assertIn("Sync preview:\n", output.getvalue())
        self.assertIn("  changed: deck +1/-0", output.getvalue())
        self.assertNotIn("  unchanged: deck", output.getvalue())

    def test_preview_lists_maybe_only_changes(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"first": [ring]})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(sync_all(
                self.paths, self.fetched({"first": [ring]}, {"first": [path]}),
                                      preview=True,
            ))
        self.assertIn("  first: deck +0/-0, Maybe +1/-0", output.getvalue())

    def test_correction_does_not_supply_a_second_requested_copy(self) -> None:
        old = card("Path to Exile", "cmm:51")
        new = card("Path to Exile", "2xm:25")
        new.quantity = 2
        self.setup_decks({"first": [old]})
        self.apply(self.fetched({"first": [new]}), ["c", "y", "y"])
        rows = _read_rows(self.paths.holdings, include_category=True)
        self.assertEqual([(row.card.printing, row.quantity) for row in rows], [("2xm:25", 2)])

    def test_rejecting_new_card_aborts_everything(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"first": [ring]})
        current = self.configs[0].directory / "current.txt"
        before = (current.read_bytes(), self.paths.holdings.read_bytes())
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(CollectionError, "cancelled"):
                sync_all(self.paths, self.fetched({"first": [ring, path]}),
                         confirm=lambda _message: "n", metadata_lookup=metadata)
        self.assertEqual((current.read_bytes(), self.paths.holdings.read_bytes()), before)

    def test_failed_database_rebuild_restores_all_source_files(self) -> None:
        ring = card("Sol Ring", "cmm:396")
        path = card("Path to Exile", "cmm:51")
        self.setup_decks({"first": [ring]})
        current = self.configs[0].directory / "current.txt"
        before = (current.read_bytes(), self.paths.holdings.read_bytes(), self.paths.database.read_bytes())
        with contextlib.redirect_stdout(io.StringIO()):
            with patch("challenge32.collection_import.build_database", side_effect=CollectionError("database failed")):
                with self.assertRaisesRegex(CollectionError, "database failed"):
                    sync_all(self.paths, self.fetched({"first": [ring, path]}),
                             confirm=lambda _message: "y", metadata_lookup=metadata)
        self.assertEqual((current.read_bytes(), self.paths.holdings.read_bytes(), self.paths.database.read_bytes()), before)
        self.assertFalse((self.configs[0].directory / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
