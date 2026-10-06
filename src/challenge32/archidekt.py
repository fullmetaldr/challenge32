from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx
import mtg_parser
from mtg_parser.card import Card

from .models import DeckMetadata
from .colors import identity_name


class ArchidektError(RuntimeError):
    """Raised when a public Archidekt deck cannot be downloaded or decoded."""


class SourcedCard(Card):
    """A parsed card with Archidekt's physical finish and primary card type."""

    def __init__(self, card: Card, *, type_category: str, finish: str) -> None:
        super().__init__(card.name, card.quantity, card.extension, card.number, card.tags)
        self.type_category = type_category
        self.finish = finish


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
                "User-Agent": "challenge32/0.1 (personal deck archive)",
                "Accept": "text/html,application/json",
            },
        )
        self.last_metadata: DeckMetadata | None = None
        self.last_parser_payload: dict[str, Any] | None = None

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
            color_identity=self._deck_color_identity(deck),
        )
        self.last_parser_payload = self._as_mtg_parser_payload(deck)
        return JsonResponse(self.last_parser_payload)

    @staticmethod
    def _deck_color_identity(deck: dict[str, Any]) -> str | None:
        commander_cards = [
            card
            for card in deck.get("cardMap", {}).values()
            if any(str(category).lower() == "commander" for category in card.get("categories", []))
        ]
        values = []
        for card in commander_cards:
            values.extend(card.get("colorIdentity") or [])
        return identity_name(values)

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
                    "typeCategory": card.get("typeCategory") or next(iter(card.get("types") or []), "Other"),
                    "modifier": card.get("modifier"),
                }
            )

        return {"categories": categories, "cards": cards}


def fetch_cards(url: str, client: ArchidektClient) -> tuple[list[Card], DeckMetadata | None]:
    client.last_parser_payload = None
    try:
        parsed = mtg_parser.parse_deck(url, client)
    except Exception as exc:
        raise ArchidektError(f"mtg_parser failed to parse {url}: {exc}") from exc

    cards = list(parsed or [])
    if not cards:
        raise ArchidektError(f"mtg_parser returned no cards for {url}")
    payload = client.last_parser_payload
    if payload is None:
        raise ArchidektError("Archidekt did not provide card finish and type data")
    included_categories = {
        category["name"]
        for category in payload["categories"]
        if category.get("includedInDeck", False)
    }
    entries = [
        entry for entry in payload["cards"]
        if not entry["categories"] or included_categories.intersection(entry["categories"])
    ]
    if len(cards) != len(entries):
        raise ArchidektError("Archidekt card details did not match the parsed deck")
    sourced: list[Card] = []
    for card, entry in zip(cards, entries, strict=True):
        if card.name != entry["card"]["oracleCard"]["name"]:
            raise ArchidektError("Archidekt card order did not match the parsed deck")
        modifier = str(entry.get("modifier") or "").casefold()
        if modifier not in {"normal", "foil", "etched"}:
            raise ArchidektError(f"Unsupported finish {entry.get('modifier')!r} for {card.name}")
        sourced.append(
            SourcedCard(
                card,
                type_category=str(entry["typeCategory"]),
                finish=modifier,
            )
        )
    return sourced, client.last_metadata
