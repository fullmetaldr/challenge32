from __future__ import annotations

from pathlib import Path
from typing import Iterable

import mtg_parser

from .colors import IDENTITY_NAMES, display_identity
from .config import discover_decks
from .models import DeckConfig


TABLE_HEADING = "## Challenge progress"
TABLE_END_HEADING = "## Current synchronizer"


def _display_identity(identity: str) -> str:
    return display_identity(identity)


def _commander(config: DeckConfig) -> str:
    current_path = config.directory / "current.txt"
    if not current_path.exists():
        return "—"
    cards = mtg_parser.parse_deck(current_path.read_text(encoding="utf-8")) or []
    commanders = [card.name for card in cards if "commander" in card.tags]
    return "<br>".join(commanders) if commanders else "—"


def _analysis_status(config: DeckConfig) -> str:
    status_path = config.directory / "notes" / "status.md"
    if not status_path.exists():
        return "—"
    status = status_path.read_text(encoding="utf-8").lower()
    return "Covered" if "covered by analysis" in status else "Unreviewed"


def _deck_link(config: DeckConfig, repo_root: Path) -> str:
    relative = config.directory.resolve().relative_to(repo_root).as_posix()
    current = f"{relative}/current.txt"
    return f"[{config.display_name}]({current}) ([source]({config.url}))"


def render_progress_table(configs: Iterable[DeckConfig], repo_root: Path) -> str:
    by_identity: dict[str, list[DeckConfig]] = {}
    for config in configs:
        by_identity.setdefault(config.color_identity, []).append(config)

    lines = [
        "| Colour identity | Status | Deck | Commander | Analysis |",
        "|---|---|---|---|---|",
    ]
    for identity in IDENTITY_NAMES.values():
        identity_configs = by_identity.get(identity, [])
        if not identity_configs:
            lines.append(f"| {_display_identity(identity)} | Not started | — | — | — |")
            continue

        identity_configs.sort(key=lambda config: config.display_name.lower())
        decks = "<br>".join(_deck_link(config, repo_root) for config in identity_configs)
        commanders = "<br>".join(_commander(config) for config in identity_configs)
        analysis = "<br>".join(_analysis_status(config) for config in identity_configs)
        lines.append(
            f"| {_display_identity(identity)} | Tracked | {decks} | {commanders} | {analysis} |"
        )
    return "\n".join(lines)


def update_progress_table(readme_path: Path, decks_root: Path) -> int:
    readme = readme_path.read_text(encoding="utf-8")
    start = readme.find(TABLE_HEADING)
    end = readme.find(TABLE_END_HEADING, start + len(TABLE_HEADING))
    if start < 0 or end < 0:
        raise ValueError(
            f"Could not find the progress table boundaries in {readme_path}; "
            f"expected {TABLE_HEADING!r} and {TABLE_END_HEADING!r}"
        )

    table = render_progress_table(discover_decks(decks_root), readme_path.parent.resolve())
    section = (
        f"{TABLE_HEADING}\n\n"
        "This table is generated from the tracked deck configurations. Run "
        "`challenge32-sync progress` to refresh it manually; "
        "`challenge32-sync add` refreshes it automatically after adding a deck.\n\n"
        f"{table}\n\n"
    )
    updated = readme[:start] + section + readme[end:]
    readme_path.write_text(updated, encoding="utf-8")
    return sum(1 for config in discover_decks(decks_root) if config.directory.exists())
