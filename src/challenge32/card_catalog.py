"""Local, disposable Scryfall metadata and image cache for the collection UI."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx


SCRYFALL_API = "https://api.scryfall.com"
HEADERS = {
    "User-Agent": "challenge32/0.1 (personal collection dashboard)",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}
SET_CACHE_AGE_SECONDS = 30 * 24 * 60 * 60
_SET_CODE = re.compile(r"[a-z0-9-]{1,24}\Z", re.IGNORECASE)


class CardCatalogError(ValueError):
    """The requested printing or Scryfall response is unusable."""


def printing_parts(printing: str) -> tuple[str, str]:
    if ":" not in printing:
        return printing.strip().lower(), ""
    set_code, collector_number = printing.split(":", 1)
    return set_code.strip().lower(), collector_number.strip()


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".download-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_set_names(cache_root: Path, *, client: httpx.Client | None = None) -> dict[str, str]:
    """Use a small cached code-to-name table, refreshing it at most monthly."""
    cache_path = cache_root / "set-names.json"
    cached: dict[str, str] = {}
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cached = {str(code).lower(): str(name) for code, name in raw.items()}
        except (OSError, ValueError, TypeError):
            pass
        if cached and time.time() - cache_path.stat().st_mtime < SET_CACHE_AGE_SECONDS:
            return cached

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=15, headers=HEADERS)
    try:
        response = client.get(f"{SCRYFALL_API}/sets")
        response.raise_for_status()
        entries = response.json().get("data", [])
        names = {
            str(item["code"]).lower(): str(item["name"])
            for item in entries
            if isinstance(item, dict) and item.get("code") and item.get("name")
        }
        if not names:
            raise CardCatalogError("Scryfall returned no set names")
        _write_atomic(cache_path, (json.dumps(names, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        return names
    except (httpx.HTTPError, ValueError, OSError):
        return cached
    finally:
        if owns_client:
            client.close()


def _validate_printing(set_code: str, collector_number: str) -> tuple[str, str]:
    set_code = set_code.strip().lower()
    collector_number = collector_number.strip()
    if not _SET_CODE.fullmatch(set_code):
        raise CardCatalogError("Invalid set code")
    if not collector_number or len(collector_number) > 64 or any(
        character in collector_number for character in ("/", "\\", "\x00")
    ) or any(ord(character) < 32 for character in collector_number):
        raise CardCatalogError("Invalid collector number")
    return set_code, collector_number


def _cache_paths(cache_root: Path, set_code: str, collector_number: str) -> tuple[Path, Path]:
    safe_number = quote(collector_number, safe="")
    set_folder = cache_root / "card-details" / set_code
    return set_folder / f"{safe_number}.json", set_folder / "images" / f"{safe_number}.jpg"


def _image_url(card: dict) -> str:
    image_uris = card.get("image_uris") or {}
    if not image_uris:
        faces = card.get("card_faces") or []
        if faces:
            image_uris = faces[0].get("image_uris") or {}
    url = image_uris.get("normal") or image_uris.get("large")
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.hostname != "cards.scryfall.io":
        raise CardCatalogError("Scryfall did not provide a usable card image")
    return url


def ensure_cached_image(
    cache_root: Path,
    set_code: str,
    collector_number: str,
    *,
    client: httpx.Client | None = None,
) -> Path:
    """Fetch a printing and its image on first request, then reuse both files."""
    set_code, collector_number = _validate_printing(set_code, collector_number)
    details_path, image_path = _cache_paths(cache_root, set_code, collector_number)
    if image_path.exists() and image_path.stat().st_size:
        return image_path

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True)
    try:
        card = None
        if details_path.exists():
            try:
                card = json.loads(details_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if card is None:
            response = client.get(
                f"{SCRYFALL_API}/cards/{quote(set_code, safe='')}/{quote(collector_number, safe='')}"
            )
            response.raise_for_status()
            card = response.json()
            if card.get("set", "").lower() != set_code or str(card.get("collector_number")) != collector_number:
                raise CardCatalogError("Scryfall returned a different printing")
            _write_atomic(details_path, (json.dumps(card, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

        image_response = client.get(_image_url(card))
        image_response.raise_for_status()
        image_bytes = image_response.content
        if not image_bytes.startswith(b"\xff\xd8\xff") or len(image_bytes) > 5_000_000:
            raise CardCatalogError("Downloaded card image was not a valid JPEG")
        _write_atomic(image_path, image_bytes)
        return image_path
    finally:
        if owns_client:
            client.close()
