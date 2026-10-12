"""Preview and confirm filing one complete physical Staging colour section."""

from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .collection import (
    CardKey, CollectionError, CollectionPaths, CollectionRow, _read_rows,
    collection_status, location_sources,
)
from .collection_import import _commit_files, _csv_bytes, _import_lock, check_import_transaction


SECTIONS = ("white", "blue", "black", "red", "green", "multicolour", "colourless", "lands")
_COLOUR_SECTION = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
_LOCATION_COLUMNS = ("card", "printing", "foil", "quantity", "notes")


@dataclass(frozen=True)
class FilingItem:
    source: Path
    row: CollectionRow
    destination: Path


@dataclass(frozen=True)
class FilingPlan:
    section: str
    items: tuple[FilingItem, ...]
    originals: tuple[tuple[Path, bytes], ...]

    @property
    def copies(self) -> int:
        return sum(item.row.quantity for item in self.items)


def _section(identity: str, type_line: str) -> str:
    if any("Land" in face.partition("—")[0].split() for face in type_line.split(" // ")):
        return "lands"
    if identity == "C":
        return "colourless"
    if len(identity) > 1:
        return "multicolour"
    return _COLOUR_SECTION[identity]


def _read_location(path: Path) -> list[CollectionRow]:
    if not path.is_file():
        raise CollectionError(f"Missing location file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        if tuple(next(csv.reader(handle), ())) != _LOCATION_COLUMNS:
            raise CollectionError(f"{path}: expected {','.join(_LOCATION_COLUMNS)} columns")
    return _read_rows(path)


def _location_bytes(rows: list[CollectionRow]) -> bytes:
    return _csv_bytes(_LOCATION_COLUMNS, [
        (row.card.name, row.card.printing, row.card.foil, row.quantity, row.notes)
        for row in rows
    ])


def plan_filing(paths: CollectionPaths, section: str) -> FilingPlan:
    if section not in SECTIONS:
        raise CollectionError(f"Choose one of: {', '.join(SECTIONS)}")
    check_import_transaction(paths)
    if not paths.database.is_file():
        raise CollectionError("Collection database is missing; run `challenge32 collection dashboard` first")
    staging_sources = [source for source in location_sources(paths) if source.kind == "staging"]
    source_rows = {source.path: _read_location(source.path) for source in staging_sources}
    source_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for rows in source_rows.values():
        for row in rows:
            source_counts[row.card.normalized] += row.quantity
    with sqlite3.connect(paths.database) as connection:
        records = connection.execute("""
            SELECT cards.name, cards.printing, cards.foil, cards.colour_identity,
                   cards.type_line, cards.rarity, placements.quantity
            FROM placements
            JOIN locations ON locations.id = placements.location_id
            JOIN cards ON cards.id = placements.card_id
            WHERE locations.name = 'staging'
        """).fetchall()
    database_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    metadata: dict[tuple[str, str, str], tuple[str | None, str | None, str | None]] = {}
    for name, printing, foil, identity, type_line, rarity, quantity in records:
        key = CardKey(name, printing, foil).normalized
        database_counts[key] += quantity
        metadata[key] = (identity, type_line, rarity)
    if dict(source_counts) != dict(database_counts):
        raise CollectionError("Staging files differ from the database; rebuild it with `challenge32 collection dashboard`")
    missing = [row.card.name for rows in source_rows.values() for row in rows
               if (info := metadata.get(row.card.normalized)) is None or info[0] is None or info[1] is None]
    if missing:
        raise CollectionError(
            f"Staging has {len(missing)} card version(s) without colour data; "
            "complete their metadata in holdings.csv before filing"
        )
    items: list[FilingItem] = []
    for path, rows in source_rows.items():
        for row in rows:
            identity, type_line, rarity = metadata[row.card.normalized]
            if _section(identity, type_line) != section:
                continue
            if rarity is None:
                raise CollectionError(f"{row.card.name} ({row.card.printing}) has no rarity in holdings.csv")
            destination = (
                paths.locations / "binders" / f"{'colorless' if section == 'colourless' else section}.csv"
                if rarity in {"rare", "mythic"} else paths.locations / "reserve.csv"
            )
            items.append(FilingItem(path, row, destination))
    touched = {item.source for item in items} | {item.destination for item in items}
    for path in touched:
        _read_location(path)
    originals = tuple(sorted(((path, path.read_bytes()) for path in touched), key=lambda entry: str(entry[0])))
    return FilingPlan(section, tuple(items), originals)


def file_section(
    paths: CollectionPaths,
    section: str,
    *,
    preview: bool = False,
    confirm: Callable[[str], str] | None = input,
) -> bool:
    plan = plan_filing(paths, section)
    binder = sum(item.row.quantity for item in plan.items if item.destination.parent.name == "binders")
    print(f"Staging section: {section}")
    print(f"{plan.copies} card(s): {binder} to binder, {plan.copies - binder} to Reserve")
    for item in plan.items:
        destination = f"Binder ({section})" if item.destination.parent.name == "binders" else "Reserve"
        print(f"  {item.row.quantity} {item.row.card.name} ({item.row.card.printing}) [{item.row.card.foil}] → {destination}")
    if any("imported" in item.source.parts for item in plan.items):
        print("Filing from an imported batch will prevent whole-batch undo of that batch.")
    if not plan.items or preview:
        return False
    if confirm is None or confirm(f"Have you physically filed the entire {section} section as shown? [y/N] ").strip().casefold() not in {"y", "yes"}:
        print("Filing cancelled; no files changed.")
        return False
    with _import_lock(paths.database.parent):
        current = plan_filing(paths, section)
        if current != plan:
            raise CollectionError("Staging or destination changed after preview; run filing again")
        moved: dict[Path, set[int]] = defaultdict(set)
        arrivals: dict[Path, list[CollectionRow]] = defaultdict(list)
        for item in plan.items:
            moved[item.source].add(item.row.source_line)
            arrivals[item.destination].append(item.row)
        changes: dict[Path, bytes] = {}
        for path in moved.keys() | arrivals.keys():
            rows = [row for row in _read_location(path) if row.source_line not in moved.get(path, set())]
            rows.extend(arrivals[path])
            changes[path] = _location_bytes(rows)
        _commit_files(paths, changes, maximum_conflicts=collection_status(paths)["conflicts"])
    print(f"Filed {plan.copies} card(s) from Staging {section}.")
    print("Any affected imported batch can no longer be undone as a whole.")
    return True
