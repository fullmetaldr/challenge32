from __future__ import annotations

import tomllib
from pathlib import Path

from .models import DeckConfig, config_from_toml


def discover_decks(root: Path) -> list[DeckConfig]:
    configs: list[DeckConfig] = []
    if not root.exists():
        return configs
    for metadata_path in sorted(root.rglob("deck.toml")):
        with metadata_path.open("rb") as handle:
            raw = tomllib.load(handle)
        configs.append(config_from_toml(metadata_path.parent, raw))
    return configs


def select_deck(root: Path, selector: str) -> DeckConfig:
    requested = Path(selector)
    if requested.is_dir():
        metadata_path = requested / "deck.toml"
    else:
        metadata_path = requested
    if not metadata_path.is_absolute():
        metadata_path = (Path.cwd() / metadata_path).resolve()
    if not metadata_path.exists():
        raise FileNotFoundError(f"Deck configuration not found: {metadata_path}")
    with metadata_path.open("rb") as handle:
        raw = tomllib.load(handle)
    return config_from_toml(metadata_path.parent, raw)

