"""Reconcile an all-deck Archidekt sync with source-controlled collection files."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

import httpx
from mtg_parser.card import Card

from .card_catalog import CardCatalogError
from .collection import (
    HOLDING_COLUMNS, CardKey, CollectionError, CollectionPaths, CollectionRow,
    _read_rows, collection_status, discover_deck_rows, location_sources,
)
from .collection_import import _commit_files, _csv_bytes, _import_lock, check_import_transaction
from .collection_metadata import CardMetadata, lookup_metadata
from .models import DeckConfig, DeckMetadata
from .sync import prepare_synchronization


Key = tuple[str, str, str]
LOCATION_COLUMNS = ("card", "printing", "foil", "quantity", "notes")


@dataclass(frozen=True)
class FetchedDeck:
    config: DeckConfig
    cards: tuple[Card, ...]
    maybe_cards: tuple[Card, ...]
    metadata: DeckMetadata | None = None


def _key(card: Card) -> CardKey:
    printing = str(card.extension or "")
    if card.number:
        printing += f":{card.number}"
    finish = str(getattr(card, "finish", "normal")).casefold()
    if finish not in {"normal", "foil", "etched"}:
        raise CollectionError(f"Unsupported finish for {card.name}: {finish}")
    return CardKey(" ".join(card.name.split()), printing, "yes" if finish != "normal" else "no")


def _count_cards(cards: Iterable[Card]) -> Counter[Key]:
    counts: Counter[Key] = Counter()
    for card in cards:
        if card.quantity <= 0 or not card.name.strip():
            raise CollectionError("Deck or Maybe board contains an invalid card")
        counts[_key(card).normalized] += card.quantity
    return counts


def _describe(card: CardKey) -> str:
    return f"{card.name} ({card.printing or 'printing unknown'}) [{card.foil}]"


def _maybe_bytes(cards: Iterable[Card], previous: list[CollectionRow] = ()) -> bytes:
    totals: Counter[Key] = Counter()
    display: dict[Key, CardKey] = {}
    notes = {row.card.normalized: row.notes for row in previous}
    for card in cards:
        key = _key(card)
        totals[key.normalized] += card.quantity
        display[key.normalized] = key
    return _csv_bytes(LOCATION_COLUMNS, [
        (display[key].name, display[key].printing, display[key].foil, quantity, notes.get(key, ""))
        for key, quantity in sorted(totals.items())
    ])


def _location_bytes(rows: list[CollectionRow]) -> bytes:
    return _csv_bytes(LOCATION_COLUMNS, [
        (row.card.name, row.card.printing, row.card.foil, row.quantity, row.notes)
        for row in rows
    ])


def _holdings_bytes(rows: dict[Key, CollectionRow]) -> bytes:
    return _csv_bytes(HOLDING_COLUMNS, [
        (row.card.name, row.card.printing, row.card.foil, row.quantity,
         row.category, row.rarity, row.colour_identity, row.type_line, row.notes)
        for _key, row in sorted(rows.items())
    ])


def _read_holdings(paths: CollectionPaths) -> dict[Key, CollectionRow]:
    holdings: dict[Key, CollectionRow] = {}
    for row in _read_rows(paths.holdings, include_category=True):
        key = row.card.normalized
        if key in holdings:
            raise CollectionError(f"Duplicate holding: {_describe(row.card)}")
        holdings[key] = row
    return holdings


def _deficits(
    holdings: dict[Key, CollectionRow], allocated: Counter[Key],
    physical_rows: dict[Path, list[CollectionRow]],
) -> dict[Key, int]:
    placed: Counter[Key] = Counter()
    for rows in physical_rows.values():
        for row in rows:
            placed[row.card.normalized] += row.quantity
    return {
        key: shortage
        for key in set(holdings) | set(allocated) | set(placed)
        if (shortage := allocated[key] + placed[key] - (holdings[key].quantity if key in holdings else 0)) > 0
    }


def _metadata(
    card: CardKey,
    paths: CollectionPaths,
    lookup: Callable[[CardKey, Path], CardMetadata],
) -> CardMetadata:
    try:
        return lookup(card, paths.database.parent)
    except (CardCatalogError, httpx.HTTPError, OSError) as exc:
        raise CollectionError(f"Cannot verify {_describe(card)} before changing collection: {exc}") from exc


def _add_holding(
    holdings: dict[Key, CollectionRow], card: CardKey, quantity: int,
    paths: CollectionPaths, lookup: Callable[[CardKey, Path], CardMetadata],
    *, category: str = "",
) -> None:
    key = card.normalized
    previous = holdings.get(key)
    if previous:
        if category and previous.category and previous.category != category:
            raise CollectionError(f"Category mismatch for {_describe(card)}; review manually")
        holdings[key] = replace(previous, quantity=previous.quantity + quantity,
                                category=previous.category or category)
        return
    details = _metadata(card, paths, lookup)
    holdings[key] = CollectionRow(
        card, quantity, category=category, rarity=details.rarity,
        colour_identity=details.colour_identity, type_line=details.type_line,
    )


def _remove_holding(holdings: dict[Key, CollectionRow], card: CardKey, quantity: int) -> CollectionRow:
    key = card.normalized
    previous = holdings.get(key)
    if previous is None or previous.quantity < quantity:
        raise CollectionError(f"Not enough known holdings to correct {_describe(card)}")
    if previous.quantity == quantity:
        del holdings[key]
    else:
        holdings[key] = replace(previous, quantity=previous.quantity - quantity)
    return previous


def _yes(answer: str) -> bool:
    return answer.strip().casefold() in {"y", "yes"}


def _ask_choice(prompt: Callable[[str], str], message: str, choices: set[str]) -> str:
    answer = prompt(message).strip().casefold()
    if answer not in choices:
        raise CollectionError("Sync cancelled; no files changed")
    return answer


def _choose_source(
    card: CardKey, available: dict[str, int], prompt: Callable[[str], str],
) -> str:
    choices = sorted(name for name, quantity in available.items() if quantity > 0)
    if not choices:
        return ""
    if len(choices) == 1:
        return choices[0]
    print(f"Possible sources for {_describe(card)}:")
    for number, name in enumerate(choices, start=1):
        print(f"  {number}. {name}: {available[name]}")
    answer = prompt("Choose source number (or Enter to cancel): ").strip()
    if not answer.isdigit() or not 1 <= int(answer) <= len(choices):
        raise CollectionError("Sync cancelled; no files changed")
    return choices[int(answer) - 1]


def _take_from_rows(rows: dict[Path, list[CollectionRow]], paths: list[Path], key: Key, quantity: int) -> None:
    remaining = quantity
    for path in sorted(paths):
        updated = []
        for row in rows[path]:
            if row.card.normalized != key or remaining == 0:
                updated.append(row)
                continue
            take = min(row.quantity, remaining)
            remaining -= take
            if row.quantity > take:
                updated.append(replace(row, quantity=row.quantity - take))
        rows[path] = updated
    if remaining:
        raise CollectionError("Source location changed during sync; no files changed")


def sync_all(
    paths: CollectionPaths,
    fetched: list[FetchedDeck],
    *,
    preview: bool = False,
    confirm: Callable[[str], str] = input,
    metadata_lookup: Callable[[CardKey, Path], CardMetadata] = lookup_metadata,
) -> bool:
    """Plan all deck/Maybe changes; commit files together only after review."""
    if not paths.holdings.is_file() or not paths.database.is_file():
        raise CollectionError("Collection is not initialised; refusing a collection-aware sync")
    check_import_transaction(paths)
    if not fetched or len({deck.config.slug for deck in fetched}) != len(fetched):
        raise CollectionError("Every configured deck must be fetched exactly once")
    old_decks = discover_deck_rows(paths.decks)
    old_by_slug: dict[str, Counter[Key]] = defaultdict(Counter)
    old_display: dict[Key, CardKey] = {}
    for row in old_decks:
        old_by_slug[row.deck_slug][row.card.normalized] += row.quantity
        old_display[row.card.normalized] = row.card
    configured = {deck.config.slug for deck in fetched}
    if set(old_by_slug) != configured:
        raise CollectionError("Fetched decks do not match the existing deck snapshots")

    old_alloc: Counter[Key] = Counter()
    new_alloc: Counter[Key] = Counter()
    display = dict(old_display)
    changes: dict[Path, bytes] = {}
    print("Sync preview:")
    for deck in fetched:
        result, snapshot_changes = prepare_synchronization(deck.config, deck.cards, deck.metadata)
        changes.update(snapshot_changes)
        deck_new = _count_cards(deck.cards)
        old_alloc.update(old_by_slug[deck.config.slug])
        new_alloc.update(deck_new)
        for card in (*deck.cards, *deck.maybe_cards):
            key = _key(card)
            display[key.normalized] = key
        maybe_path = paths.locations / "maybe" / f"{deck.config.slug}.csv"
        if not maybe_path.is_file():
            raise CollectionError(f"Missing Maybe location file: {maybe_path}")
        old_maybe = _read_rows(maybe_path)
        old_maybe_counts: Counter[Key] = Counter()
        for row in old_maybe:
            old_maybe_counts[row.card.normalized] += row.quantity
        new_maybe_counts = _count_cards(deck.maybe_cards)
        old_alloc.update(old_maybe_counts)
        new_alloc.update(new_maybe_counts)
        for row in old_maybe:
            display.setdefault(row.card.normalized, row.card)
        if old_maybe_counts != new_maybe_counts:
            changes[maybe_path] = _maybe_bytes(deck.maybe_cards, old_maybe)
        deck_diffs = sum((deck_new - old_by_slug[deck.config.slug]).values())
        deck_diffs_out = sum((old_by_slug[deck.config.slug] - deck_new).values())
        maybe_diffs = sum((new_maybe_counts - old_maybe_counts).values())
        maybe_diffs_out = sum((old_maybe_counts - new_maybe_counts).values())
        if not (result["changed"] or deck_diffs or deck_diffs_out or maybe_diffs or maybe_diffs_out):
            continue
        print(f"  {deck.config.display_name}: deck +{deck_diffs}/-{deck_diffs_out}, "
              f"Maybe +{maybe_diffs}/-{maybe_diffs_out}; snapshot {'changed' if result['changed'] else 'unchanged'}")
        for label, before, after in (
            ("Deck", old_by_slug[deck.config.slug], deck_new),
            ("Maybe", old_maybe_counts, new_maybe_counts),
        ):
            for key, quantity in sorted((before - after).items()):
                print(f"    {label} out: {quantity} {_describe(display[key])}")
            for key, quantity in sorted((after - before).items()):
                print(f"    {label} in:  {quantity} {_describe(display[key])}")

    holdings = _read_holdings(paths)
    sources = [source for source in location_sources(paths) if source.kind != "maybe"]
    physical_rows: dict[Path, list[CollectionRow]] = {source.path: _read_rows(source.path) for source in sources}
    original_physical_rows = {path: list(rows) for path, rows in physical_rows.items()}
    watched_paths = ({paths.holdings}
                     | {deck.config.directory / "current.txt" for deck in fetched}
                     | {paths.locations / "maybe" / f"{deck.config.slug}.csv" for deck in fetched}
                     | set(physical_rows))
    watched = {path: path.read_bytes() if path.exists() else None for path in watched_paths}
    baseline_deficits = _deficits(holdings, old_alloc, physical_rows)
    location_paths: dict[str, list[Path]] = defaultdict(list)
    for source in sources:
        location_paths[source.name].append(source.path)
        for row in physical_rows[source.path]:
            display.setdefault(row.card.normalized, row.card)
    outgoing = old_alloc - new_alloc
    incoming = new_alloc - old_alloc
    if outgoing or incoming:
        print("Unmatched after cross-deck/Maybe transfers:")
    for key, quantity in sorted(outgoing.items()):
        print(f"  Out: {quantity} {_describe(display[key])}")
    for key, quantity in sorted(incoming.items()):
        print(f"  In:  {quantity} {_describe(display[key])}")
    if preview:
        print("Preview only: identity corrections and physical sources require review on apply.")
        return False

    if outgoing or incoming:
        print("\nCollection reconciliation:")

    with _import_lock(paths.database.parent):
        holdings_changed = False
        # Pair different versions of the same card before declaring either a move.
        for old_key in sorted(list(outgoing)):
            for new_key in sorted(list(incoming)):
                if old_key[0] != new_key[0] or old_key == new_key:
                    continue
                quantity = min(outgoing[old_key], incoming[new_key])
                if not quantity:
                    continue
                old_card, new_card = display[old_key], display[new_key]
                print(f"  Same card, different version ({quantity}): {_describe(old_card)} -> {_describe(new_card)}")
                choice = _ask_choice(confirm, "Printing/foil correction [c] or physical replacement [r]? ", {"c", "r"})
                if choice == "c":
                    previous = _remove_holding(holdings, old_card, quantity)
                    _add_holding(holdings, new_card, quantity, paths, metadata_lookup, category=previous.category)
                    holdings_changed = True
                    old_alloc[old_key] -= quantity
                    old_alloc[new_key] += quantity
                outgoing[old_key] -= quantity
                incoming[new_key] -= quantity
                if choice == "r":
                    outgoing[old_key] += quantity
                    incoming[new_key] += quantity

        staging_path = paths.locations / "staging" / "deck-sync.csv"
        for key, quantity in sorted(outgoing.items()):
            if quantity <= 0:
                continue
            card = display[key]
            if key not in holdings or holdings[key].quantity < quantity:
                raise CollectionError(f"Outgoing copy is not in known holdings: {_describe(card)}")
            row = holdings[key]
            if not row.rarity or not row.colour_identity or not row.type_line:
                details = _metadata(card, paths, metadata_lookup)
                holdings[key] = replace(row, rarity=details.rarity,
                                        colour_identity=details.colour_identity, type_line=details.type_line)
                holdings_changed = True
            staging_rows = physical_rows.setdefault(staging_path, _read_rows(staging_path))
            staging_rows.append(CollectionRow(card, quantity))
            print(f"  To Staging: {quantity} {_describe(card)}")

        for key, quantity in sorted(incoming.items()):
            if quantity <= 0:
                continue
            card = display[key]
            remaining = quantity
            while remaining:
                placed_by_location = {
                    name: sum(row.quantity for path in paths_for_location for row in physical_rows[path]
                              if row.card.normalized == key)
                    for name, paths_for_location in location_paths.items()
                }
                placed_total = sum(placed_by_location.values())
                free = max(0, holdings.get(key, CollectionRow(card, 0)).quantity
                           - old_alloc[key] - placed_total)
                available = {name: count for name, count in placed_by_location.items() if count}
                if free:
                    available["Unplaced owned copy"] = free
                source = _choose_source(card, available, confirm)
                if source:
                    take = min(remaining, available[source])
                    if source != "Unplaced owned copy":
                        _take_from_rows(physical_rows, location_paths[source], key, take)
                    old_alloc[key] += take
                    remaining -= take
                    print(f"  To deck/Maybe: {take} {_describe(card)} from {source}")
                    continue
                answer = _ask_choice(confirm, f"No known copy of {_describe(card)} is available. New card? [Y/n] ",
                                     {"", "y", "yes", "n", "no"})
                if answer in {"n", "no"}:
                    raise CollectionError("Sync cancelled; no files changed")
                _add_holding(holdings, card, remaining, paths, metadata_lookup)
                holdings_changed = True
                print(f"  Added to holdings: {remaining} {_describe(card)}")
                remaining = 0

        final_deficits = _deficits(holdings, new_alloc, physical_rows)
        worsened = {key: deficit for key, deficit in final_deficits.items()
                    if deficit > baseline_deficits.get(key, 0)}
        if worsened:
            examples = ", ".join(_describe(display[key]) for key in sorted(worsened)[:3])
            raise CollectionError(f"Sync would increase collection shortages for {examples}; no files changed")
        if holdings_changed:
            changes[paths.holdings] = _holdings_bytes(holdings)
        for path, rows in physical_rows.items():
            if rows != original_physical_rows.get(path, []):
                changes[path] = _location_bytes(rows)
        changes = {path: content for path, content in changes.items()
                   if not path.exists() or path.read_bytes() != content}
        if any((path.read_bytes() if path.exists() else None) != original
               for path, original in watched.items()):
            raise CollectionError("Collection or deck files changed during sync; no files changed")
        if not changes:
            print("No deck or collection source changes.")
            return False
        print()
        if not _yes(confirm("Apply all deck and collection changes shown above? [y/N] ")):
            print("Sync cancelled; no files changed.")
            return False
        _commit_files(paths, changes, maximum_conflicts=collection_status(paths)["conflicts"])
    print("All decks and collection source files updated together.")
    return True
