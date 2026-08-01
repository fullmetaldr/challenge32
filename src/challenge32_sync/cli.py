from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from .archidekt import ArchidektError, ArchidektClient, fetch_cards
from .config import discover_decks, select_deck
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
