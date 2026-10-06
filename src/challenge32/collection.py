from __future__ import annotations

import csv
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .config import discover_decks


FOIL_VALUES = {"yes", "no", "unknown"}
LOCATION_FILES = (
    ("reserve.csv", "reserve"),
    ("unknown.csv", "unknown"),
)
STAGING_FILES = (
    "white.csv",
    "blue.csv",
    "black.csv",
    "red.csv",
    "green.csv",
    "multicolour.csv",
    "colourless.csv",
    "lands.csv",
)


class CollectionError(ValueError):
    """Raised when collection source data or initialization prerequisites are invalid."""


@dataclass(frozen=True, order=True)
class CardKey:
    name: str
    printing: str = ""
    foil: str = "unknown"

    @property
    def normalized(self) -> tuple[str, str, str]:
        return (" ".join(self.name.casefold().split()), self.printing.casefold(), self.foil)


@dataclass(frozen=True)
class CollectionRow:
    card: CardKey
    quantity: int
    category: str = ""
    notes: str = ""
    source_path: Path | None = None
    source_line: int | None = None


@dataclass(frozen=True)
class DeckRow:
    deck_slug: str
    display_name: str
    card: CardKey
    quantity: int
    source_path: Path
    source_line: int


@dataclass(frozen=True)
class LocationSource:
    name: str
    kind: str
    path: Path


@dataclass(frozen=True)
class CollectionPaths:
    root: Path = Path("collection")
    decks: Path = Path("decks")
    database: Path = Path("data/collection.sqlite")

    @property
    def holdings(self) -> Path:
        return self.root / "holdings.csv"

    @property
    def locations(self) -> Path:
        return self.root / "locations"


def _csv_header(path: Path, columns: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(list(columns))


def _card_key(name: str, printing: str = "", foil: str = "unknown") -> CardKey:
    return CardKey(name=" ".join(name.strip().split()), printing=printing.strip(), foil=foil.strip().lower() or "unknown")


def _quantity(value: str, path: Path, row_number: int) -> int:
    try:
        quantity = int(value)
    except (TypeError, ValueError) as exc:
        raise CollectionError(f"{path}:{row_number}: quantity must be a positive integer") from exc
    if quantity <= 0:
        raise CollectionError(f"{path}:{row_number}: quantity must be a positive integer")
    return quantity


def _read_rows(path: Path, *, include_category: bool = False) -> list[CollectionRow]:
    if not path.exists():
        return []
    required = {"card", "printing", "foil", "quantity"}
    if include_category:
        required.add("category")
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            missing = sorted(required - fields)
            if missing:
                raise CollectionError(f"{path}: missing required column(s): {', '.join(missing)}")
            rows: list[CollectionRow] = []
            for row_number, row in enumerate(reader, start=2):
                name = (row.get("card") or "").strip()
                foil = (row.get("foil") or "unknown").strip().lower() or "unknown"
                if not name:
                    raise CollectionError(f"{path}:{row_number}: card must not be empty")
                if foil not in FOIL_VALUES:
                    raise CollectionError(
                        f"{path}:{row_number}: foil must be one of {', '.join(sorted(FOIL_VALUES))}"
                    )
                rows.append(
                    CollectionRow(
                        card=_card_key(name, row.get("printing", ""), foil),
                        quantity=_quantity(row.get("quantity", ""), path, row_number),
                        category=(row.get("category") or "").strip() if include_category else "",
                        notes=(row.get("notes") or "").strip(),
                        source_path=path,
                        source_line=row_number,
                    )
                )
            return rows
    except OSError as exc:
        raise CollectionError(f"Could not read {path}: {exc}") from exc


_DECK_LINE = re.compile(r"^\s*(?P<quantity>\d+)\s+(?P<card>.+?)\s*$")
_PRINTING_SUFFIX = re.compile(r"^(?P<name>.+?)\s+\((?P<set>[^)]*)\)(?:\s+(?P<number>\S+))?$")
_FOIL_SUFFIX = re.compile(r"\s+\*[FE]\*$")
_DECK_FORMAT_2 = "# Format: 2"


def parse_decklist(path: Path) -> list[DeckRow]:
    if not path.exists():
        raise CollectionError(f"Missing generated decklist: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    format_2 = _DECK_FORMAT_2 in (line.strip() for line in lines)
    result: list[DeckRow] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("//"):
            continue
        match = _DECK_LINE.match(line)
        if not match:
            raise CollectionError(f"{path}:{line_number}: could not parse decklist line")
        card_text = match.group("card")
        is_foil = bool(_FOIL_SUFFIX.search(card_text))
        if is_foil:
            card_text = _FOIL_SUFFIX.sub("", card_text)
        printed = _PRINTING_SUFFIX.match(card_text)
        if printed:
            printing = printed.group("set")
            if printed.group("number"):
                printing += f":{printed.group('number')}"
            card_text = printed.group("name")
        else:
            printing = ""
        result.append(
            DeckRow(
                deck_slug="",
                display_name="",
                card=_card_key(card_text, printing, "yes" if is_foil else "no" if format_2 else "unknown"),
                quantity=int(match.group("quantity")),
                source_path=path,
                source_line=line_number,
            )
        )
    return result


def discover_deck_rows(decks_root: Path) -> list[DeckRow]:
    rows: list[DeckRow] = []
    for config in discover_decks(decks_root):
        for row in parse_decklist(config.directory / "current.txt"):
            rows.append(
                DeckRow(
                    deck_slug=config.slug,
                    display_name=config.display_name,
                    card=row.card,
                    quantity=row.quantity,
                    source_path=row.source_path,
                    source_line=row.source_line,
                )
            )
    return rows


def _aggregate(rows: Iterable[CollectionRow | DeckRow]) -> dict[CardKey, int]:
    totals: dict[CardKey, int] = defaultdict(int)
    for row in rows:
        totals[row.card] += row.quantity
    return dict(totals)


def _write_holdings(path: Path, rows: Iterable[CollectionRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("card", "printing", "foil", "quantity", "category", "notes"))
        for row in sorted(rows, key=lambda item: item.card.normalized):
            writer.writerow((row.card.name, row.card.printing, row.card.foil, row.quantity, row.category, row.notes))


def location_sources(paths: CollectionPaths) -> list[LocationSource]:
    sources = [
        LocationSource(name=kind, kind=kind, path=paths.locations / filename)
        for filename, kind in LOCATION_FILES
    ]
    sources.extend(
        LocationSource(name=f"staging:{path.stem}", kind="staging", path=path)
        for path in (paths.locations / "staging").glob("*.csv")
    )
    sources.extend(
        LocationSource(name=f"maybe:{path.stem}", kind="maybe", path=path)
        for path in (paths.locations / "maybe").glob("*.csv")
    )
    return sorted(sources, key=lambda source: source.name)


def read_non_deck_placements(paths: CollectionPaths) -> list[tuple[LocationSource, CollectionRow]]:
    placements: list[tuple[LocationSource, CollectionRow]] = []
    for source in location_sources(paths):
        for row in _read_rows(source.path):
            placements.append((source, row))
    return placements


def _schema_text() -> str:
    return """# Challenge32 collection data

The collection files are source-controlled and intentionally represent only
cards that have been explicitly encountered or recorded. An absent card is
not evidence that it is unowned.

## holdings.csv

`holdings.csv` records known owned quantities. `card` and `printing` identify a
card version; printing is stored as `set-code:collector-number` when available.
`foil` is `yes`, `no`, or `unknown`. `category` is descriptive metadata such as
`regular` or `proxy` and does not change quantity accounting.

```csv
card,printing,foil,quantity,category,notes
Sol Ring,cmm:396,no,1,regular,
```

## locations/

Location files use the same identity columns, but omit `category`:

```csv
card,printing,foil,quantity,notes
Sol Ring,cmm:396,no,1,
```

Deck allocation is derived from the tracked decklists and is never duplicated
in a manually maintained location file. The initial layout contains Reserve,
Unknown, colour-based Staging sections, and one Maybe Box file per deck.

The SQLite database is generated state. It is not a hand-edited source file.
"""


def _initialization_plan(paths: CollectionPaths, deck_rows: list[DeckRow]) -> str:
    totals = _aggregate(deck_rows)
    return "\n".join(
        [
            f"Repository: {Path.cwd()}",
            f"Decks discovered: {len({row.deck_slug for row in deck_rows})}",
            f"Deck cards: {sum(row.quantity for row in deck_rows)}",
            f"Distinct card versions: {len(totals)}",
            f"Files to create under {paths.root}:",
            "  schema.md",
            "  holdings.csv",
            "  locations/reserve.csv",
            "  locations/unknown.csv",
            *(f"  locations/staging/{filename}" for filename in STAGING_FILES),
            *(f"  locations/maybe/{deck_slug}.csv" for deck_slug in sorted({row.deck_slug for row in deck_rows})),
            f"  {paths.database}",
        ]
    )


def _check_initialization(paths: CollectionPaths, deck_rows: list[DeckRow]) -> None:
    if not paths.decks.exists():
        raise CollectionError(f"Deck root does not exist: {paths.decks}")
    if not deck_rows:
        raise CollectionError("No decklists were found; refusing to initialize an empty collection")
    if paths.root.exists():
        raise CollectionError(
            f"Collection directory already exists: {paths.root}; refusing to overwrite it"
        )
    if paths.database.exists():
        raise CollectionError(
            f"Collection database already exists: {paths.database}; refusing to overwrite it"
        )


def initialize_collection(
    paths: CollectionPaths,
    *,
    confirm: Callable[[str], str] | None = None,
) -> dict[str, int | str]:
    deck_rows = discover_deck_rows(paths.decks)
    _check_initialization(paths, deck_rows)
    print(_initialization_plan(paths, deck_rows))
    if confirm is not None:
        if confirm("Continue? [y/N] ").strip().lower() not in {"y", "yes"}:
            raise CollectionError("Initialization cancelled")
        if confirm("Type INITIALISE CHALLENGE32 COLLECTION to continue: ").strip() != "INITIALISE CHALLENGE32 COLLECTION":
            raise CollectionError("Initialization cancelled")

    paths.root.mkdir(parents=True)
    (paths.root / "schema.md").write_text(_schema_text(), encoding="utf-8")
    holdings = [CollectionRow(card=card, quantity=quantity) for card, quantity in _aggregate(deck_rows).items()]
    _write_holdings(paths.holdings, holdings)
    for filename, _kind in LOCATION_FILES:
        _csv_header(paths.locations / filename, ("card", "printing", "foil", "quantity", "notes"))
    for filename in STAGING_FILES:
        _csv_header(paths.locations / "staging" / filename, ("card", "printing", "foil", "quantity", "notes"))
    for deck_slug in sorted({row.deck_slug for row in deck_rows}):
        _csv_header(paths.locations / "maybe" / f"{deck_slug}.csv", ("card", "printing", "foil", "quantity", "notes"))
    build_database(paths, deck_rows=deck_rows)
    return {"decks": len({row.deck_slug for row in deck_rows}), "card_versions": len(holdings), "cards": sum(row.quantity for row in deck_rows)}


def _database_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            printing TEXT NOT NULL,
            foil TEXT NOT NULL CHECK (foil IN ('yes', 'no', 'unknown')),
            UNIQUE (name COLLATE NOCASE, printing, foil)
        );
        CREATE TABLE set_names (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE holdings (
            card_id INTEGER NOT NULL REFERENCES cards(id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            category TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            source_path TEXT,
            source_line INTEGER
        );
        CREATE TABLE locations (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            source_path TEXT
        );
        CREATE TABLE placements (
            card_id INTEGER NOT NULL REFERENCES cards(id),
            location_id INTEGER NOT NULL REFERENCES locations(id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            notes TEXT NOT NULL DEFAULT '',
            source_path TEXT,
            source_line INTEGER
        );
        CREATE TABLE decks (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            directory TEXT NOT NULL
        );
        CREATE TABLE deck_cards (
            deck_id INTEGER NOT NULL REFERENCES decks(id),
            card_id INTEGER NOT NULL REFERENCES cards(id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            source_path TEXT NOT NULL,
            source_line INTEGER NOT NULL
        );
        CREATE TABLE reconciliation_issues (
            id INTEGER PRIMARY KEY,
            card_id INTEGER REFERENCES cards(id),
            issue_type TEXT NOT NULL,
            message TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0
        );
        """
    )


def _card_id(connection: sqlite3.Connection, card: CardKey) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO cards(name, printing, foil) VALUES (?, ?, ?)",
        (card.name, card.printing, card.foil),
    )
    row = connection.execute(
        "SELECT id FROM cards WHERE name = ? COLLATE NOCASE AND printing = ? AND foil = ?",
        (card.name, card.printing, card.foil),
    ).fetchone()
    assert row is not None
    return int(row[0])


def build_database(
    paths: CollectionPaths,
    *,
    deck_rows: list[DeckRow] | None = None,
    set_names: dict[str, str] | None = None,
) -> None:
    deck_rows = deck_rows if deck_rows is not None else discover_deck_rows(paths.decks)
    holdings = _read_rows(paths.holdings, include_category=True)
    non_deck = read_non_deck_placements(paths)
    paths.database.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".collection-", suffix=".sqlite", dir=paths.database.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        with sqlite3.connect(temporary_path) as connection:
            _database_schema(connection)
            if set_names:
                connection.executemany(
                    "INSERT INTO set_names(code, name) VALUES (?, ?)",
                    sorted(set_names.items()),
                )
            for row in holdings:
                card_id = _card_id(connection, row.card)
                connection.execute(
                    "INSERT INTO holdings VALUES (?, ?, ?, ?, ?, ?)",
                    (card_id, row.quantity, row.category, row.notes, str(row.source_path), row.source_line),
                )
            deck_ids: dict[str, int] = {}
            for row in deck_rows:
                deck_id = deck_ids.get(row.deck_slug)
                if deck_id is None:
                    cursor = connection.execute(
                        "INSERT INTO decks(slug, display_name, directory) VALUES (?, ?, ?)",
                        (row.deck_slug, row.display_name, str(row.source_path.parent)),
                    )
                    deck_id = int(cursor.lastrowid)
                    deck_ids[row.deck_slug] = deck_id
                card_id = _card_id(connection, row.card)
                connection.execute(
                    "INSERT INTO deck_cards VALUES (?, ?, ?, ?, ?)",
                    (deck_id, card_id, row.quantity, str(row.source_path), row.source_line),
                )
            for slug, deck_id in deck_ids.items():
                location_id = connection.execute(
                    "INSERT INTO locations(name, kind, source_path) VALUES (?, 'deck', NULL)",
                    (f"deck:{slug}",),
                ).lastrowid
                for row in [entry for entry in deck_rows if entry.deck_slug == slug]:
                    card_id = _card_id(connection, row.card)
                    connection.execute(
                        "INSERT INTO placements VALUES (?, ?, ?, '', ?, ?)",
                        (card_id, location_id, row.quantity, str(row.source_path), row.source_line),
                    )
            for source, row in non_deck:
                location_id = connection.execute(
                    "INSERT OR IGNORE INTO locations(name, kind, source_path) VALUES (?, ?, ?)",
                    (source.name, source.kind, str(source.path)),
                ).lastrowid
                if location_id is None:
                    location_id = connection.execute(
                        "SELECT id FROM locations WHERE name = ?", (source.name,)
                    ).fetchone()[0]
                card_id = _card_id(connection, row.card)
                connection.execute(
                    "INSERT INTO placements VALUES (?, ?, ?, ?, ?, ?)",
                    (card_id, location_id, row.quantity, row.notes, str(row.source_path), row.source_line),
                )
            connection.execute(
                "CREATE INDEX idx_cards_name ON cards(name COLLATE NOCASE)"
            )
            connection.commit()
        os.replace(temporary_path, paths.database)
    finally:
        temporary_path.unlink(missing_ok=True)


def collection_status(paths: CollectionPaths) -> dict[str, int]:
    if not paths.root.exists() or not paths.database.exists():
        raise CollectionError("Collection is not initialized; run `challenge32 collection --init`")
    deck_rows = discover_deck_rows(paths.decks)
    holdings = _aggregate(_read_rows(paths.holdings, include_category=True))
    locations = _aggregate(row for _source, row in read_non_deck_placements(paths))
    allocated = _aggregate(deck_rows)
    conflicts = sum(
        1
        for card in set(holdings) | set(locations) | set(allocated)
        if holdings.get(card, 0) < allocated.get(card, 0) + locations.get(card, 0)
    )
    return {
        "decks": len({row.deck_slug for row in deck_rows}),
        "known_card_versions": len(holdings),
        "known_cards": sum(holdings.values()),
        "deck_allocated": sum(allocated.values()),
        "non_deck_placed": sum(locations.values()),
        "conflicts": conflicts,
    }
