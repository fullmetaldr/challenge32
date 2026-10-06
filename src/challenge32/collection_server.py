"""Local-only dashboard server with an on-demand Scryfall image cache."""

from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from .card_catalog import CardCatalogError, ensure_cached_image


class CollectionServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], output_dir: Path, cache_root: Path) -> None:
        self.output_dir = output_dir.resolve()
        self.cache_root = cache_root.resolve()
        self.cache_lock = threading.Lock()
        payload = json.loads((self.output_dir / "data.json").read_text(encoding="utf-8"))
        self.known_printings = {
            (card["set_code"], card["card_number"])
            for card in payload["inventory"]
            if card["set_code"] and card["card_number"]
        }
        super().__init__(address, CollectionHandler)


class CollectionHandler(SimpleHTTPRequestHandler):
    server: CollectionServer

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(args[2].output_dir), **kwargs)

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        if request.path != "/api/card-image":
            return super().do_GET()
        parameters = parse_qs(request.query)
        set_code = parameters.get("set", [""])[0].lower()
        card_number = parameters.get("number", [""])[0]
        if (set_code, card_number) not in self.server.known_printings:
            self.send_error(404, "Printing is not in this collection dashboard")
            return
        try:
            # Keep simultaneous hovers from fetching the same printing twice.
            with self.server.cache_lock:
                image_path = ensure_cached_image(self.server.cache_root, set_code, card_number)
                if not image_path.exists():
                    raise CardCatalogError("Card image was not cached")
            image_bytes = image_path.read_bytes()
        except (CardCatalogError, httpx.HTTPError, OSError, ValueError) as exc:
            self.send_error(502, f"Could not load card image: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(image_bytes)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        self.wfile.write(image_bytes)


def serve_collection_dashboard(output_dir: Path, cache_root: Path, port: int = 8001) -> None:
    with CollectionServer(("127.0.0.1", port), output_dir, cache_root) as server:
        print(f"Serving collection dashboard at http://localhost:{port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
