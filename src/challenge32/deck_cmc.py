"""Read-only total mana value report for the current deck snapshots."""

from __future__ import annotations

import re
from pathlib import Path

from .collection import CollectionError, _read_rows, parse_decklist
from .config import discover_decks


def _front_is_land(type_line: str) -> bool:
    front_type = type_line.split(" // ", 1)[0].partition("—")[0]
    return re.search(r"\bLand\b", front_type) is not None


def deck_cmc_totals(decks_root: Path, holdings_path: Path) -> list[tuple[str, float]]:
    """Sum quantity-weighted mana values, treating front-face lands as zero."""
    configs = discover_decks(decks_root)
    if not configs:
        raise CollectionError(f"No deck.toml files found under {decks_root}")
    if not holdings_path.is_file():
        raise CollectionError(f"Missing collection holdings: {holdings_path}")

    holdings = {}
    for row in _read_rows(holdings_path, include_category=True):
        key = row.card.normalized
        if key in holdings:
            raise CollectionError(f"Duplicate holding for {row.card.name} ({row.card.printing})")
        holdings[key] = row

    totals = []
    missing = []
    for config in configs:
        total = 0.0
        for deck_row in parse_decklist(config.directory / "current.txt"):
            owned = holdings.get(deck_row.card.normalized)
            if owned is None or owned.mana_value is None:
                missing.append(f"{config.display_name}: {deck_row.card.name} ({deck_row.card.printing})")
                continue
            if not _front_is_land(owned.type_line):
                total += deck_row.quantity * owned.mana_value
        totals.append((config.display_name, total))
    if missing:
        examples = "; ".join(missing[:5])
        remainder = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
        raise CollectionError(f"Missing owned printing or mana value for {examples}{remainder}")
    return sorted(totals, key=lambda item: (item[1], item[0].casefold()))
