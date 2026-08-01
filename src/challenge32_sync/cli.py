from __future__ import annotations

import argparse
import json
import tomllib
import re
import unicodedata
from pathlib import Path

from .archidekt import ArchidektError, ArchidektClient, fetch_cards
from .config import discover_decks, select_deck
from .models import DeckConfig
from .progress import update_progress_table
from .sync import synchronize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="challenge32-sync")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Synchronize decklists from their configured sources")
    target = sync_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--deck", help="Path to a deck directory or deck.toml")
    target.add_argument("--all", action="store_true", help="Synchronize every deck under decks/")
    sync_parser.add_argument("--dry-run", action="store_true", help="Fetch and compare without writing files")
    sync_parser.add_argument("--root", type=Path, default=Path("decks"), help="Deck root (default: decks)")

    add_parser = subparsers.add_parser("add", help="Add and initially synchronize a new Archidekt deck")
    add_parser.add_argument("url", help="Public Archidekt deck URL")
    add_parser.add_argument("--root", type=Path, default=Path("decks"), help="Deck root (default: decks)")
    add_parser.add_argument("--dry-run", action="store_true", help="Fetch and show the destination without writing files")

    progress_parser = subparsers.add_parser("progress", help="Refresh the README progress table")
    progress_parser.add_argument("--root", type=Path, default=Path("decks"), help="Deck root (default: decks)")
    progress_parser.add_argument("--readme", type=Path, default=Path("README.md"), help="README path (default: README.md)")
    return parser


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "unnamed-deck"


def write_deck_config(config: DeckConfig) -> None:
    config.directory.mkdir(parents=True, exist_ok=True)
    config.metadata_path.write_text(
        "\n".join(
            [
                f"slug = {json.dumps(config.slug, ensure_ascii=False)}",
                f"display_name = {json.dumps(config.display_name, ensure_ascii=False)}",
                f"source = {json.dumps(config.source, ensure_ascii=False)}",
                f"url = {json.dumps(config.url, ensure_ascii=False)}",
                f"color_identity = {json.dumps(config.color_identity, ensure_ascii=False)}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def add_deck(args: argparse.Namespace) -> int:
    with ArchidektClient() as client:
        cards, metadata = fetch_cards(args.url, client)

    if metadata is None:
        raise ArchidektError("Archidekt did not provide deck metadata")
    if metadata.private:
        raise ArchidektError("Refusing to add a private deck; use a public deck URL")
    if not metadata.color_identity:
        raise ArchidektError(
            "Could not infer the colour identity from the Commander; add the deck manually with deck.toml"
        )

    config = DeckConfig(
        directory=args.root / metadata.color_identity / slugify(metadata.name),
        slug=slugify(metadata.name),
        display_name=metadata.name,
        source="archidekt",
        url=args.url,
        color_identity=metadata.color_identity,
    )
    if config.directory.exists():
        raise FileExistsError(f"Deck directory already exists: {config.directory}")

    result = synchronize(config, cards, metadata, dry_run=args.dry_run)
    print(f"Deck: {metadata.name}")
    print(f"Colour identity: {metadata.color_identity}")
    print(f"Local directory: {config.directory}")
    if args.dry_run:
        print(f"Would create version: {result['version']}")
        return 0

    write_deck_config(config)
    if args.root.resolve().is_relative_to(Path.cwd().resolve()):
        update_progress_table(Path("README.md"), args.root)
    print(f"Created version: {result['version']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "add":
        try:
            return add_deck(args)
        except (ArchidektError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"error: {exc}")
            return 1

    if args.command == "progress":
        try:
            count = update_progress_table(args.readme, args.root)
            print(f"Updated {args.readme} from {count} tracked deck configuration(s)")
            return 0
        except (FileNotFoundError, OSError, ValueError) as exc:
            print(f"error: {exc}")
            return 1

    if args.command != "sync":
        return 2

    try:
        configs = discover_decks(args.root) if args.all else [select_deck(args.root, args.deck)]
        if not configs:
            raise ValueError(f"No deck.toml files found under {args.root}")
        for config in configs:
            print(f"Syncing {config.display_name} from {config.url}")
            with ArchidektClient() as client:
                cards, metadata = fetch_cards(config.url, client)
                result = synchronize(config, cards, metadata, dry_run=args.dry_run)
            state = "changed" if result["changed"] else "unchanged"
            print(f"  {state}: {result['version']} ({sum(card.quantity for card in cards)} cards)")
        return 0
    except (ArchidektError, FileNotFoundError, OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}")
        return 1
