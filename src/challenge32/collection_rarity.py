"""Explicitly enrich the source-controlled collection with printing rarities."""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Callable

import httpx

from .card_catalog import CardCatalogError, HEADERS, _write_atomic, ensure_cached_card_details, printing_parts
from .collection import (
    RARITY_VALUES,
    CollectionPaths,
    _read_rows,
    build_database,
    discover_deck_rows,
    read_non_deck_placements,
    read_rarities,
)


def _inventory_printings(paths: CollectionPaths) -> dict[tuple[str, str], tuple[str, str]]:
    cards = [row.card for row in _read_rows(paths.holdings, include_category=True)]
    cards.extend(row.card for row in discover_deck_rows(paths.decks))
    cards.extend(row.card for _, row in read_non_deck_placements(paths))
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for card in cards:
        key = (" ".join(card.name.casefold().split()), card.printing.casefold())
        result.setdefault(key, (card.name, card.printing))
    return result


def _write_rarities(path: Path, rows: dict[tuple[str, str], tuple[str, str, str]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(("card", "printing", "rarity"))
    for card, printing, rarity in sorted(rows.values(), key=lambda row: (row[0].casefold(), row[1].casefold())):
        writer.writerow((card, printing, rarity))
    _write_atomic(path, buffer.getvalue().encode("utf-8"))


def _matches_card_name(local_name: str, source_name: str) -> bool:
    local = " ".join(local_name.casefold().split())
    faces = [" ".join(face.casefold().split()) for face in source_name.split(" // ")]
    return bool(local) and all(face == local for face in faces)


def update_rarities(
    paths: CollectionPaths,
    *,
    client: httpx.Client | None = None,
    progress: Callable[[str], None] = print,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Fetch only missing exact-printing rarities; keep unresolved cards unknown."""
    if not paths.root.is_dir():
        raise ValueError("Collection is not initialised; run `challenge32 collection --init`")
    known = read_rarities(paths.rarities)
    rows: dict[tuple[str, str], tuple[str, str, str]] = {}
    if paths.rarities.exists():
        with paths.rarities.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (" ".join(row["card"].casefold().split()), row["printing"].casefold())
                rows[key] = (row["card"], row["printing"], row["rarity"])

    inventory = _inventory_printings(paths)
    pending = [(key, *values) for key, values in sorted(inventory.items()) if key not in known]
    progress(f"Rarity lookup: {len(pending)} missing of {len(inventory)} known card printings")
    added = failed = 0
    unavailable = False
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True)
    try:
        for key, name, printing in pending:
            set_code, number = printing_parts(printing)
            if not set_code or not number:
                failed += 1
                progress(f"Unresolved: {name} ({printing or 'no printing'}) — no exact set and collector number")
                continue
            try:
                details = ensure_cached_card_details(paths.database.parent, set_code, number, client=client)
                rarity = str(details.get("rarity", "")).casefold()
                if rarity not in RARITY_VALUES:
                    raise CardCatalogError(f"unsupported rarity {rarity!r}")
                if not _matches_card_name(name, str(details.get("name", ""))):
                    raise CardCatalogError(f"printing belongs to {details.get('name')!r}")
                rows[key] = (name, printing, rarity)
                added += 1
                if added % 25 == 0:
                    _write_rarities(paths.rarities, rows)
                    progress(f"Saved {added} new rarities")
            except httpx.RequestError as exc:
                failed += 1
                unavailable = True
                progress(f"Rarity service unavailable; stopping after {name} ({printing}) — {exc}")
                break
            except httpx.HTTPStatusError as exc:
                failed += 1
                progress(f"Unresolved: {name} ({printing}) — HTTP {exc.response.status_code}")
                if exc.response.status_code == 429 or exc.response.status_code >= 500:
                    unavailable = True
                    progress("Rarity service unavailable; stopping without retrying the remaining cards")
                    break
            except (CardCatalogError, OSError, ValueError) as exc:
                failed += 1
                progress(f"Unresolved: {name} ({printing}) — {exc}")
            else:
                pause(0.12)
    finally:
        if added % 25:
            _write_rarities(paths.rarities, rows)
        if owns_client:
            client.close()
    build_database(paths)
    return {"added": added, "unresolved": failed, "known": len(inventory), "unavailable": unavailable}
