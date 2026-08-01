from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeckConfig:
    directory: Path
    slug: str
    display_name: str
    source: str
    url: str
    color_identity: str

    @property
    def metadata_path(self) -> Path:
        return self.directory / "deck.toml"


@dataclass(frozen=True)
class DeckMetadata:
    name: str
    owner: str | None
    deck_id: int | None
    private: bool | None
    unlisted: bool | None
    updated_at: str | None
    card_count: int


def config_from_toml(directory: Path, raw: dict[str, Any]) -> DeckConfig:
    required = ("slug", "display_name", "source", "url", "color_identity")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(
            f"{directory / 'deck.toml'} is missing required fields: {', '.join(missing)}"
        )

    source = str(raw["source"]).lower()
    if source != "archidekt":
        raise ValueError(f"Unsupported source {source!r}; only 'archidekt' is supported")

    return DeckConfig(
        directory=directory,
        slug=str(raw["slug"]),
        display_name=str(raw["display_name"]),
        source=source,
        url=str(raw["url"]),
        color_identity=str(raw["color_identity"]),
    )

