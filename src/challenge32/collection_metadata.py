"""Verified card metadata for one exact Scryfall printing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from .card_catalog import CardCatalogError, ensure_cached_card_details, printing_parts
from .collection import COLOURS, RARITY_VALUES, CardKey


@dataclass(frozen=True)
class CardMetadata:
    rarity: str
    colour_identity: str
    type_line: str


def _matches_card_name(local_name: str, source_name: str) -> bool:
    local = " ".join(local_name.casefold().split())
    source = " ".join(source_name.casefold().split())
    if local == source:
        return bool(local)
    faces = [" ".join(face.casefold().split()) for face in source_name.split(" // ")]
    return bool(local) and all(face == local for face in faces)


def metadata_from_details(card: CardKey, details: dict) -> CardMetadata:
    if not _matches_card_name(card.name, str(details.get("name", ""))):
        raise CardCatalogError(f"{card.printing}: printing belongs to {details.get('name')!r}, not {card.name!r}")
    rarity = str(details.get("rarity", "")).casefold()
    if rarity not in RARITY_VALUES:
        raise CardCatalogError(f"{card.printing}: missing or unsupported rarity")
    raw_identity = details.get("color_identity")
    if not isinstance(raw_identity, list) or any(color not in COLOURS for color in raw_identity):
        raise CardCatalogError(f"{card.printing}: missing or invalid colour identity")
    identity = "".join(color for color in COLOURS if color in raw_identity) or "C"
    type_line = details.get("type_line")
    if not isinstance(type_line, str) or not type_line.strip():
        faces = details.get("card_faces")
        if not isinstance(faces, list) or not faces or any(
            not isinstance(face, dict) or not isinstance(face.get("type_line"), str) or not face["type_line"].strip()
            for face in faces
        ):
            raise CardCatalogError(f"{card.printing}: missing card type line")
        type_line = " // ".join(face["type_line"].strip() for face in faces)
    return CardMetadata(rarity, identity, type_line.strip())


def lookup_metadata(card: CardKey, cache_root: Path, *, client: httpx.Client | None = None) -> CardMetadata:
    set_code, number = printing_parts(card.printing)
    if not set_code or not number:
        raise CardCatalogError(f"{card.name}: exact set code and collector number required")
    details = ensure_cached_card_details(cache_root, set_code, number, client=client)
    return metadata_from_details(card, details)
