from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mtg_parser

from .colors import IDENTITY_NAMES, display_identity
from .config import discover_decks
from .models import DeckConfig
from .sync import _section


ASSET_DIR = Path(__file__).parent / "templates"
GENERATED_MARKER = ".challenge32-dashboard"


def _analysis_status(config: DeckConfig) -> str:
    status_path = config.directory / "notes" / "status.md"
    if not status_path.exists():
        return "—"
    status = status_path.read_text(encoding="utf-8").lower()
    return "Covered" if "covered by analysis" in status else "Unreviewed"


def _state(config: DeckConfig) -> dict[str, Any]:
    state_path = config.directory / "state.json"
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _cards(config: DeckConfig) -> list[dict[str, Any]]:
    current_path = config.directory / "current.txt"
    if not current_path.exists():
        return []
    cards = mtg_parser.parse_deck(current_path.read_text(encoding="utf-8")) or []
    return [
        {
            "name": card.name,
            "quantity": card.quantity,
            "section": _section(card).title(),
            "extension": card.extension,
            "number": card.number,
            "tags": sorted(str(tag) for tag in card.tags),
        }
        for card in cards
    ]


def _commander(cards: list[dict[str, Any]]) -> list[str]:
    return [
        card["name"]
        for card in cards
        if "commander" in {tag.lower() for tag in card["tags"]}
    ]


def _relative_deck_path(config: DeckConfig, decks_root: Path) -> str:
    relative = config.directory.resolve().relative_to(decks_root.resolve())
    return (Path("decks") / relative).as_posix()


def _deck_payload(config: DeckConfig, decks_root: Path) -> dict[str, Any]:
    cards = _cards(config)
    state = _state(config)
    relative_path = _relative_deck_path(config, decks_root)
    versions_dir = config.directory / "versions"
    versions = sorted(path.name for path in versions_dir.glob("*.txt")) if versions_dir.exists() else []
    notes_dir = config.directory / "notes"
    notes = []
    if notes_dir.exists():
        notes = sorted(
            [
                {"name": path.stem, "path": f"{relative_path}/notes/{path.name}"}
                for path in notes_dir.glob("*.md")
                if path.name != "status.md"
            ],
            key=lambda note: note["name"].lower(),
        )
    return {
        "slug": config.slug,
        "display_name": config.display_name,
        "source": config.source,
        "source_url": config.url,
        "color_identity": config.color_identity,
        "commander": _commander(cards),
        "card_count": state.get("card_count") or sum(card["quantity"] for card in cards),
        "analysis_status": _analysis_status(config),
        "retrieved_at": state.get("retrieved_at"),
        "current_version": state.get("current_version"),
        "current_hash": state.get("current_hash"),
        "path": relative_path,
        "current_path": f"{relative_path}/current.txt",
        "state_path": f"{relative_path}/state.json",
        "notes": notes,
        "versions": [f"{relative_path}/versions/{version}" for version in versions],
        "cards": cards,
    }


def build_data(decks_root: Path) -> dict[str, Any]:
    configs = discover_decks(decks_root)
    configs_by_identity: dict[str, list[DeckConfig]] = {}
    for config in configs:
        configs_by_identity.setdefault(config.color_identity, []).append(config)

    identities = []
    for color_codes, identity in IDENTITY_NAMES.items():
        identity_configs = sorted(
            configs_by_identity.get(identity, []),
            key=lambda config: config.display_name.lower(),
        )
        identities.append(
            {
                "key": identity,
                "name": display_identity(identity),
                "colors": color_codes,
                "status": "Tracked" if identity_configs else "Not started",
                "decks": [_deck_payload(config, decks_root) for config in identity_configs],
            }
        )

    return {
        "project": "Challenge32",
        "generated_at": None,
        "identity_count": len(IDENTITY_NAMES),
        "tracked_identity_count": sum(bool(item["decks"]) for item in identities),
        "deck_count": len(configs),
        "identities": identities,
    }


def _copy_decks(decks_root: Path, output_dir: Path, configs: list[DeckConfig]) -> None:
    for config in configs:
        relative = config.directory.resolve().relative_to(decks_root.resolve())
        destination = output_dir / "decks" / relative
        shutil.copytree(config.directory, destination, dirs_exist_ok=True)


def build_dashboard(decks_root: Path, output_dir: Path) -> int:
    decks_root = decks_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir == decks_root or output_dir.is_relative_to(decks_root):
        raise ValueError("Dashboard output must not be inside the deck root")
    output_dir.mkdir(parents=True, exist_ok=True)
    marker = output_dir / GENERATED_MARKER
    if any(output_dir.iterdir()) and not marker.exists():
        raise ValueError(
            f"Refusing to write dashboard into non-generated directory: {output_dir}"
        )
    for child in output_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    configs = discover_decks(decks_root)
    data = build_data(decks_root)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    (output_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for asset_name in ("index.html", "style.css", "app.js"):
        source = ASSET_DIR / asset_name
        destination = output_dir / asset_name if asset_name == "index.html" else output_dir / "assets" / asset_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    _copy_decks(decks_root, output_dir, configs)
    marker.write_text("Generated by challenge32-sync dashboard.\n", encoding="utf-8")
    return len(configs)
