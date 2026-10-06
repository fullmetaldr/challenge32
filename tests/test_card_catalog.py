from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from challenge32.card_catalog import ensure_cached_image, load_set_names, printing_parts


class CardCatalogTests(unittest.TestCase):
    def test_set_names_and_image_are_cached_without_repeated_requests(self) -> None:
        requests: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            if request.url.path == "/sets":
                return httpx.Response(200, json={"data": [{"code": "cmm", "name": "Commander Masters"}]})
            if request.url.path == "/cards/cmm/396":
                return httpx.Response(200, json={
                    "name": "Sol Ring",
                    "set": "cmm",
                    "collector_number": "396",
                    "oracle_text": "{T}: Add {C}{C}.",
                    "image_uris": {"normal": "https://cards.scryfall.io/normal/front/example.jpg"},
                })
            if request.url.path == "/normal/front/example.jpg":
                return httpx.Response(200, content=b"\xff\xd8\xffsample-image")
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as temporary:
            cache_root = Path(temporary)
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                self.assertEqual(load_set_names(cache_root, client=client)["cmm"], "Commander Masters")
                self.assertEqual(load_set_names(cache_root, client=client)["cmm"], "Commander Masters")
                first = ensure_cached_image(cache_root, "cmm", "396", client=client)
                second = ensure_cached_image(cache_root, "cmm", "396", client=client)
            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), b"\xff\xd8\xffsample-image")
            details = json.loads((cache_root / "card-details" / "cmm" / "396.json").read_text())
            self.assertEqual(details["oracle_text"], "{T}: Add {C}{C}.")
            self.assertEqual(len(requests), 3)

    def test_printing_can_contain_non_ascii_collector_number(self) -> None:
        self.assertEqual(printing_parts("pvow:46★"), ("pvow", "46★"))
