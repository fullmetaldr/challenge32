from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx
import mtg_parser

from .models import DeckMetadata


class ArchidektError(RuntimeError):
    """Raised when a public Archidekt deck cannot be downloaded or decoded."""


@dataclass
class JsonResponse:
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class ArchidektClient:
    """HTTP client compatible with mtg_parser's Archidekt parser.

    mtg_parser 0.0.1a55 requests `/api/decks/<id>/`, but the current Archidekt
    deployment responds to that route with a client-route error. The public
    deck page contains the same data in `__NEXT_DATA__`; this client translates
    that page payload into the shape expected by mtg_parser.
    """

    _API_PATTERN = re.compile(r"/api/decks/(?P<deck_id>\d+)/?$")
    _PAGE_PATTERN = re.compile(r"/decks/(?P<deck_id>\d+)(?:/[^/]*)?/?$")
    _NEXT_DATA_PATTERN = re.compile(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        re.DOTALL,
    )

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "challenge32-sync/0.1 (personal deck archive)",
                "Accept": "text/html,application/json",
            },
        )
        self.last_metadata: DeckMetadata | None = None

    def __enter__(self) -> "ArchidektClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, *args: Any, **kwargs: Any) -> Any:
        """Return a requests-compatible response for mtg_parser."""
        parsed = urlparse(url)
        match = self._API_PATTERN.search(parsed.path)
        if match and parsed.netloc.endswith("archidekt.com"):
            return self._get_parser_payload(match.group("deck_id"))

        response = self._client.get(url, *args, **kwargs)
        response.raise_for_status()
        return response

    def _get_parser_payload(self, deck_id: str) -> JsonResponse:
        page_url = f"https://archidekt.com/decks/{deck_id}"
        response = self._client.get(page_url)
        response.raise_for_status()

        next_data_match = self._NEXT_DATA_PATTERN.search(response.text)
        if not next_data_match:
            raise ArchidektError(f"Could not find structured data on {page_url}")

        try:
            next_data = json.loads(unescape(next_data_match.group(1)))
            deck = next_data["props"]["pageProps"]["redux"]["deck"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ArchidektError(f"Could not decode structured deck data from {page_url}") from exc

        if not isinstance(deck, dict) or not deck.get("cardMap"):
            raise ArchidektError(f"The public page did not contain cards for deck {deck_id}")

        self.last_metadata = DeckMetadata(
            name=str(deck.get("name") or deck_id),
            owner=str(deck.get("owner")) if deck.get("owner") else None,
            deck_id=int(deck["id"]) if deck.get("id") is not None else int(deck_id),
            private=deck.get("private"),
            unlisted=deck.get("unlisted"),
            updated_at=str(deck.get("updatedAt")) if deck.get("updatedAt") else None,
            card_count=sum(int(card.get("qty", 0)) for card in deck["cardMap"].values()),
        )
        return JsonResponse(self._as_mtg_parser_payload(deck))

    @staticmethod
    def _as_mtg_parser_payload(deck: dict[str, Any]) -> dict[str, Any]:
        categories = deck.get("categories", {})
        if isinstance(categories, dict):
            categories = list(categories.values())

        cards = []
        for card in deck.get("cardMap", {}).values():
            name = card.get("name") or card.get("displayName")
            if not name:
                continue
            cards.append(
                {
                    "card": {
                        "oracleCard": {"name": name},
                        "edition": {"editioncode": card.get("setCode")},
                        "collectorNumber": card.get("collectorNumber"),
                    },
                    "quantity": card.get("qty", 1),
                    "categories": card.get("categories", []),
                }
            )

        return {"categories": categories, "cards": cards}


def fetch_cards(url: str, client: ArchidektClient) -> tuple[list[Any], DeckMetadata | None]:
    try:
        parsed = mtg_parser.parse_deck(url, client)
    except Exception as exc:
        raise ArchidektError(f"mtg_parser failed to parse {url}: {exc}") from exc

    cards = list(parsed or [])
    if not cards:
        raise ArchidektError(f"mtg_parser returned no cards for {url}")
    return cards, client.last_metadata

