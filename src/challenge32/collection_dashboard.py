from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .card_catalog import load_set_names, printing_parts
from .collection import CollectionPaths, build_database


ASSET_DIR = Path(__file__).parent / "templates"
GENERATED_MARKER = ".challenge32-collection-dashboard"


def _location_label(name: str, deck_names: dict[str, str]) -> str:
    if name.startswith("binder:"):
        return f"Binder ({name.partition(':')[2].title()})"
    if name.startswith("maybe:"):
        slug = name.partition(":")[2]
        return f"Maybe Box ({deck_names.get(slug, slug)})"
    return {"staging": "Staging", "reserve": "Reserve", "unknown": "Unknown"}.get(name, name)


def _status(known_owned: int | None, allocated: int, placed: int) -> tuple[str, int | None]:
    if known_owned is None:
        return "ownership-unknown", None
    free_known = known_owned - allocated - placed
    if free_known < 0:
        return "conflict", free_known
    if free_known > 0:
        return "location-unknown", free_known
    return "accounted", 0


def _collection_payload(database: Path, set_names: dict[str, str] | None = None) -> dict[str, Any]:
    set_names = set_names or {}
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        card_rows = connection.execute(
            """
            SELECT
                c.id,
                c.name,
                c.printing,
                c.foil,
                c.rarity,
                h.quantity AS known_owned,
                COALESCE(d.quantity, 0) AS deck_allocated,
                COALESCE(p.quantity, 0) AS non_deck_placed
            FROM cards AS c
            LEFT JOIN (
                SELECT card_id, SUM(quantity) AS quantity
                FROM holdings
                GROUP BY card_id
            ) AS h ON h.card_id = c.id
            LEFT JOIN (
                SELECT card_id, SUM(quantity) AS quantity
                FROM deck_cards
                GROUP BY card_id
            ) AS d ON d.card_id = c.id
            LEFT JOIN (
                SELECT p.card_id, SUM(p.quantity) AS quantity
                FROM placements AS p
                JOIN locations AS l ON l.id = p.location_id
                WHERE l.kind <> 'deck'
                GROUP BY p.card_id
            ) AS p ON p.card_id = c.id
            ORDER BY c.name COLLATE NOCASE, c.printing, c.foil
            """
        ).fetchall()
        deck_rows = connection.execute(
            """
            SELECT d.slug, d.display_name, SUM(dc.quantity) AS quantity,
                   COUNT(DISTINCT dc.card_id) AS card_versions
            FROM decks AS d
            JOIN deck_cards AS dc ON dc.deck_id = d.id
            GROUP BY d.id
            ORDER BY d.display_name COLLATE NOCASE
            """
        ).fetchall()
        location_rows = connection.execute(
            """
            SELECT l.name, l.kind, COALESCE(SUM(p.quantity), 0) AS quantity,
                   COUNT(DISTINCT p.card_id) AS card_versions
            FROM locations AS l
            LEFT JOIN placements AS p ON p.location_id = l.id
            WHERE l.kind <> 'deck'
            GROUP BY l.id
            HAVING COALESCE(SUM(p.quantity), 0) > 0 OR l.kind = 'binder'
            ORDER BY l.name COLLATE NOCASE
            """
        ).fetchall()
        deck_card_rows = connection.execute(
            """
            SELECT dc.card_id, d.display_name, SUM(dc.quantity) AS quantity
            FROM deck_cards AS dc
            JOIN decks AS d ON d.id = dc.deck_id
            GROUP BY dc.card_id, d.id
            ORDER BY d.display_name COLLATE NOCASE
            """
        ).fetchall()
        location_card_rows = connection.execute(
            """
            SELECT p.card_id, l.name, SUM(p.quantity) AS quantity
            FROM placements AS p
            JOIN locations AS l ON l.id = p.location_id
            WHERE l.kind <> 'deck'
            GROUP BY p.card_id, l.id
            ORDER BY l.name COLLATE NOCASE
            """
        ).fetchall()

    deck_names = {row["slug"]: row["display_name"] for row in deck_rows}
    decks_by_card: dict[int, list[dict[str, Any]]] = {}
    for row in deck_card_rows:
        decks_by_card.setdefault(int(row["card_id"]), []).append(
            {"name": row["display_name"], "quantity": int(row["quantity"])}
        )
    locations_by_card: dict[int, list[dict[str, Any]]] = {}
    for row in location_card_rows:
        locations_by_card.setdefault(int(row["card_id"]), []).append(
            {
                "name": row["name"],
                "label": _location_label(row["name"], deck_names),
                "quantity": int(row["quantity"]),
            }
        )

    inventory: list[dict[str, Any]] = []
    for row in card_rows:
        set_code, card_number = printing_parts(row["printing"])
        known_owned = int(row["known_owned"]) if row["known_owned"] is not None else None
        allocated = int(row["deck_allocated"])
        placed = int(row["non_deck_placed"])
        status, free_known = _status(known_owned, allocated, placed)
        inventory.append(
            {
                "id": int(row["id"]),
                "name": row["name"],
                "printing": row["printing"],
                "set_code": set_code,
                "set_name": set_names.get(set_code, set_code.upper() if set_code else ""),
                "card_number": card_number,
                "foil": row["foil"],
                "rarity": row["rarity"],
                "known_owned": known_owned,
                "deck_allocated": allocated,
                "non_deck_placed": placed,
                "free_known": free_known,
                "status": status,
                "decks": decks_by_card.get(int(row["id"]), []),
                "locations": locations_by_card.get(int(row["id"]), []),
            }
        )

    known_owned_total = sum(row["known_owned"] or 0 for row in inventory)
    different_cards = len({
        " ".join(row["name"].casefold().split())
        for row in inventory if row["known_owned"] is not None
    })
    deck_allocated_total = sum(row["deck_allocated"] for row in inventory)
    non_deck_total = sum(row["non_deck_placed"] for row in inventory)
    in_staging = sum(row["quantity"] for row in location_rows if row["kind"] == "staging")
    in_reserve = sum(row["quantity"] for row in location_rows if row["kind"] == "reserve")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "known_card_versions": len(inventory),
            "known_owned": known_owned_total,
            "different_cards": different_cards,
            "deck_allocated": deck_allocated_total,
            "non_deck_placed": non_deck_total,
            "in_staging": in_staging,
            "in_reserve": in_reserve,
            "location_unknown": sum(row["free_known"] for row in inventory if row["status"] == "location-unknown"),
            "ownership_unknown": sum(1 for row in inventory if row["status"] == "ownership-unknown"),
            "conflicts": sum(1 for row in inventory if row["status"] == "conflict"),
        },
        "decks": [dict(row) for row in deck_rows],
        "locations": [
            {**dict(row), "label": _location_label(row["name"], deck_names)}
            for row in location_rows
        ],
        "inventory": inventory,
    }


def _copy_assets(output_dir: Path) -> None:
    (output_dir / "assets").mkdir(parents=True, exist_ok=True)
    for source_name, destination in (
        ("collection_index.html", output_dir / "index.html"),
        ("collection_app.js", output_dir / "assets" / "app.js"),
        ("collection_style.css", output_dir / "assets" / "style.css"),
    ):
        shutil.copyfile(ASSET_DIR / source_name, destination)


def build_collection_dashboard(paths: CollectionPaths, output_dir: Path) -> dict[str, Any]:
    """Rebuild the derived database and write a local static dashboard."""
    set_names = load_set_names(paths.database.parent)
    build_database(paths, set_names=set_names)
    payload = _collection_payload(paths.database, set_names)
    output_dir = output_dir.resolve()
    if any(output_dir.iterdir()) if output_dir.exists() else False:
        if not (output_dir / GENERATED_MARKER).exists():
            raise ValueError(f"Refusing to write dashboard into non-generated directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for child in output_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (output_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _copy_assets(output_dir)
    (output_dir / GENERATED_MARKER).write_text(
        "Generated by challenge32 collection dashboard.\n", encoding="utf-8"
    )
    return payload
