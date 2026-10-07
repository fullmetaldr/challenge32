"""Reviewable, additive scanner-batch imports and guarded reversals."""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .collection import (
    CardKey,
    CollectionError,
    CollectionPaths,
    CollectionRow,
    _read_rows,
    build_database,
    collection_status,
)


LOG_COLUMNS = (
    "batch", "content_hash", "source_file", "imported_at", "card_versions",
    "copies", "intake_hash", "status", "undone_at",
)
BATCH_COLUMNS = ("card", "printing", "foil", "finish", "quantity")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SET_CODE = re.compile(r"[a-z0-9-]{2,12}\Z")
_NUMBER = re.compile(r"[^/\\\x00-\x1f]{1,64}\Z")
_ALIASES = {
    "card": ("cardname", "name", "card"),
    "set": ("setcode", "editioncode", "set"),
    "number": ("cardnumber", "collectornumber", "number"),
    "foil": ("foil", "finish", "foiltype"),
    "quantity": ("quantity", "qty", "count"),
}


@dataclass(frozen=True)
class ImportCard:
    card: CardKey
    finish: str
    quantity: int


@dataclass(frozen=True)
class ImportPlan:
    batch: str
    source: Path
    cards: tuple[ImportCard, ...]
    content_hash: str
    existing_versions: int
    new_versions: int

    @property
    def copies(self) -> int:
        return sum(card.quantity for card in self.cards)


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _column_names(fieldnames: list[str] | None, path: Path) -> dict[str, str]:
    available = {_normalise_header(name): name for name in fieldnames or []}
    selected: dict[str, str] = {}
    for field, aliases in _ALIASES.items():
        selected[field] = next((available[alias] for alias in aliases if alias in available), "")
    missing = [field for field, name in selected.items() if not name]
    if missing:
        raise CollectionError(
            f"{path}: missing ManaBox column(s): {', '.join(missing)}; "
            "expected name, set code, card/collector number, foil, quantity"
        )
    return selected


def _finish(value: str, path: Path, line: int) -> tuple[str, str]:
    key = re.sub(r"[\s_-]+", "", value.casefold())
    if key in {"no", "false", "0", "normal", "nonfoil", "none"}:
        return "no", "normal"
    if key in {"yes", "true", "1", "foil"}:
        return "yes", "foil"
    if key in {"etched", "etchedfoil", "foiletched"}:
        return "yes", "etched"
    raise CollectionError(f"{path}:{line}: unrecognised foil value {value!r}")


def _canonical(cards: list[ImportCard]) -> tuple[ImportCard, ...]:
    totals: dict[tuple[tuple[str, str, str], str], int] = defaultdict(int)
    display: dict[tuple[tuple[str, str, str], str], CardKey] = {}
    for item in cards:
        key = (item.card.normalized, item.finish)
        totals[key] += item.quantity
        display.setdefault(key, item.card)
    return tuple(
        ImportCard(display[key], key[1], totals[key])
        for key in sorted(totals)
    )


def _fingerprint(cards: tuple[ImportCard, ...]) -> str:
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    for item in cards:
        totals[(item.card.printing.casefold(), item.card.foil, item.finish)] += item.quantity
    data = [[*key, quantity] for key, quantity in sorted(totals.items())]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode("utf-8")).hexdigest()


def _read_manabox(path: Path) -> tuple[ImportCard, ...]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = _column_names(reader.fieldnames, path)
            cards: list[ImportCard] = []
            for line, row in enumerate(reader, start=2):
                if None in row:
                    raise CollectionError(f"{path}:{line}: too many CSV fields")
                if not any(str(value or "").strip() for value in row.values()):
                    continue
                name = " ".join(str(row[columns["card"]] or "").split())
                set_code = str(row[columns["set"]] or "").strip().lower()
                number = str(row[columns["number"]] or "").strip()
                foil_value = str(row[columns["foil"]] or "").strip()
                quantity_text = str(row[columns["quantity"]] or "").strip()
                if not name or not _SET_CODE.fullmatch(set_code) or not _NUMBER.fullmatch(number):
                    raise CollectionError(f"{path}:{line}: name, set code and collector number are required")
                foil, finish = _finish(foil_value, path, line)
                try:
                    quantity = int(quantity_text)
                except ValueError as exc:
                    raise CollectionError(f"{path}:{line}: quantity must be a positive integer") from exc
                if quantity <= 0:
                    raise CollectionError(f"{path}:{line}: quantity must be a positive integer")
                cards.append(ImportCard(CardKey(name, f"{set_code}:{number}", foil), finish, quantity))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CollectionError(f"Could not read {path}: {exc}") from exc
    if not cards:
        raise CollectionError(f"{path}: no cards found")
    return _canonical(cards)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug or len(slug) > 80 or not _SLUG.fullmatch(slug):
        raise CollectionError("Batch name must be a short name containing letters, numbers and hyphens")
    return slug


def select_import_file(
    import_dir: Path,
    selected: Path | None,
    *,
    confirm: Callable[[str], str] | None,
) -> Path:
    import_dir = import_dir.resolve()
    if selected is not None:
        path = selected.resolve()
        if path.parent != import_dir or path.suffix.casefold() != ".csv" or not path.is_file():
            raise CollectionError(f"Import file must be a CSV directly under {import_dir}: {selected}")
        return path
    files: list[Path] = []
    if import_dir.is_dir():
        files = sorted(
            path.resolve() for path in import_dir.iterdir()
            if path.is_file() and path.suffix.casefold() == ".csv" and path.resolve().parent == import_dir
        )
    if not files:
        raise CollectionError(f"No pending CSV files in {import_dir}")
    if len(files) == 1:
        return files[0]
    if confirm is None:
        raise CollectionError("Multiple CSV files found; specify one with --file")
    print("Pending imports:")
    for index, path in enumerate(files, start=1):
        print(f"  {index}. {path.name}")
    answer = confirm("Choose a file number (blank to cancel): ").strip()
    if not answer.isdecimal() or not 1 <= int(answer) <= len(files):
        raise CollectionError("Import cancelled")
    return files[int(answer) - 1]


def _read_log(paths: CollectionPaths) -> list[dict[str, str]]:
    path = paths.imports / "log.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LOG_COLUMNS:
            raise CollectionError(f"{path}: unsupported import log columns")
        return list(reader)


def _check_duplicate(batch: str, digest: str, log: list[dict[str, str]]) -> None:
    for entry in log:
        if entry["batch"] == batch:
            raise CollectionError(f"Batch {batch!r} was already imported ({entry['status']})")
        if entry["content_hash"] == digest:
            raise CollectionError(
                f"These card quantities match previous batch {entry['batch']!r}; "
                "refusing a possible duplicate import"
            )


def _holdings_map(paths: CollectionPaths) -> dict[tuple[str, str, str], CollectionRow]:
    rows = _read_rows(paths.holdings, include_category=True)
    result: dict[tuple[str, str, str], CollectionRow] = {}
    for row in rows:
        key = row.card.normalized
        if key in result:
            raise CollectionError(f"{paths.holdings}: duplicate card version {row.card.name}")
        result[key] = row
    return result


def plan_import(paths: CollectionPaths, source: Path, batch: str) -> ImportPlan:
    check_import_transaction(paths)
    if not paths.root.is_dir() or not paths.database.is_file():
        raise CollectionError("Collection is not initialised; run `challenge32 collection --init`")
    batch = _slug(batch)
    cards = _read_manabox(source)
    digest = _fingerprint(cards)
    _check_duplicate(batch, digest, _read_log(paths))
    holdings = _holdings_map(paths)
    names_by_printing = {
        row.card.printing.casefold(): row.card.name
        for row in holdings.values() if row.card.printing
    }
    for item in cards:
        printing_key = item.card.printing.casefold()
        existing_name = names_by_printing.get(printing_key)
        if existing_name and existing_name.casefold() != item.card.name.casefold():
            raise CollectionError(
                f"{item.card.printing}: scanner name {item.card.name!r} differs from "
                f"known card {existing_name!r}; review the printing before import"
            )
        names_by_printing[printing_key] = item.card.name
    if (paths.locations / "intake" / f"{batch}.csv").exists():
        raise CollectionError(f"Intake location already exists for batch {batch!r}")
    if (paths.imports / "batches" / f"{batch}.csv").exists():
        raise CollectionError(f"Import receipt already exists for batch {batch!r}")
    identities = {item.card.normalized for item in cards}
    existing = sum(key in holdings for key in identities)
    return ImportPlan(batch, source, cards, digest, existing, len(identities) - existing)


def _csv_bytes(columns: tuple[str, ...], rows: list[tuple[object, ...]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _holding_bytes(rows: dict[tuple[str, str, str], CollectionRow]) -> bytes:
    return _csv_bytes(
        ("card", "printing", "foil", "quantity", "category", "notes"),
        [
            (row.card.name, row.card.printing, row.card.foil, row.quantity, row.category, row.notes)
            for _key, row in sorted(rows.items())
        ],
    )


def _location_bytes(cards: tuple[ImportCard, ...]) -> bytes:
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    display: dict[tuple[str, str, str], CardKey] = {}
    for item in cards:
        key = item.card.normalized
        totals[key] += item.quantity
        display.setdefault(key, item.card)
    return _csv_bytes(
        ("card", "printing", "foil", "quantity", "notes"),
        [(display[key].name, display[key].printing, display[key].foil, totals[key], "") for key in sorted(totals)],
    )


def _batch_bytes(cards: tuple[ImportCard, ...]) -> bytes:
    return _csv_bytes(
        BATCH_COLUMNS,
        [(item.card.name, item.card.printing, item.card.foil, item.finish, item.quantity) for item in cards],
    )


def _log_bytes(log: list[dict[str, str]]) -> bytes:
    return _csv_bytes(LOG_COLUMNS, [tuple(entry[column] for column in LOG_COLUMNS) for entry in log])


def _existing_set_names(database: Path) -> dict[str, str]:
    if not database.exists():
        return {}
    with sqlite3.connect(database) as connection:
        try:
            return dict(connection.execute("SELECT code, name FROM set_names"))
        except sqlite3.OperationalError:
            return {}


def check_import_transaction(paths: CollectionPaths) -> None:
    pending = paths.database.parent / "collection-import-transaction"
    if pending.exists():
        raise CollectionError(
            f"An interrupted collection import may need recovery: {pending}. "
            "Do not import again until its source files are inspected or restored."
        )


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".challenge32-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _commit_files(
    paths: CollectionPaths,
    changes: dict[Path, bytes | None],
    *,
    maximum_conflicts: int,
) -> None:
    check_import_transaction(paths)
    originals = {path: path.read_bytes() if path.exists() else None for path in changes}
    database_original = paths.database.read_bytes() if paths.database.exists() else None
    set_names = _existing_set_names(paths.database)
    transaction_dir = paths.database.parent / "collection-import-transaction"
    preparation = Path(tempfile.mkdtemp(prefix=".collection-import-prep-", dir=paths.database.parent))
    try:
        manifest = []
        for index, (path, original) in enumerate((*originals.items(), (paths.database, database_original))):
            backup = f"{index}.backup" if original is not None else ""
            if original is not None:
                _write_atomic(preparation / backup, original)
            manifest.append({"target": str(path.resolve()), "backup": backup})
        _write_atomic(
            preparation / "manifest.json",
            (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        )
        os.replace(preparation, transaction_dir)
    finally:
        if preparation.exists():
            shutil.rmtree(preparation)
    try:
        for path, content in changes.items():
            if content is None:
                path.unlink()
            else:
                _write_atomic(path, content)
        build_database(paths, set_names=set_names)
        if collection_status(paths)["conflicts"] > maximum_conflicts:
            raise CollectionError("Import would create allocation conflicts")
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                _write_atomic(path, original)
        if database_original is None:
            paths.database.unlink(missing_ok=True)
        else:
            _write_atomic(paths.database, database_original)
        shutil.rmtree(transaction_dir)
        raise
    shutil.rmtree(transaction_dir)


@contextmanager
def _import_lock(import_dir: Path) -> Iterator[None]:
    import_dir.mkdir(parents=True, exist_ok=True)
    with (import_dir / ".challenge32-import.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _print_plan(plan: ImportPlan) -> None:
    print(f"Batch: {plan.batch}")
    print(f"Source: {plan.source}")
    print(f"Card versions: {plan.new_versions + plan.existing_versions} "
          f"({plan.new_versions} new, {plan.existing_versions} already known)")
    print(f"Copies to add: {plan.copies}")
    print(f"Destination: Intake/{plan.batch}")
    if any(item.finish == "etched" for item in plan.cards):
        print("Note: etched cards remain labelled etched in the receipt but count as foil in holdings.")
    for item in plan.cards:
        print(f"  +{item.quantity} {item.card.name} ({item.card.printing}) [{item.finish}]")


def ingest_batch(
    paths: CollectionPaths,
    import_dir: Path,
    *,
    selected: Path | None = None,
    batch: str | None = None,
    preview: bool = False,
    confirm: Callable[[str], str] | None = input,
) -> bool:
    source = select_import_file(import_dir, selected, confirm=None if preview else confirm)
    proposed = _slug(batch or source.stem)
    if batch is None and not preview and confirm is not None:
        answer = confirm(f"Batch name [{proposed}] (Enter to accept): ").strip()
        if answer:
            proposed = _slug(answer)
    plan = plan_import(paths, source, proposed)
    _print_plan(plan)
    if preview:
        return False
    if confirm is None or confirm("Import this batch? [y/N] ").strip().casefold() not in {"y", "yes"}:
        print("Import cancelled; no files changed.")
        return False
    with _import_lock(import_dir):
        current = plan_import(paths, source, proposed)
        if current.content_hash != plan.content_hash:
            raise CollectionError("Import file changed after preview; run ingest again")
        holdings = _holdings_map(paths)
        for item in current.cards:
            key = item.card.normalized
            previous = holdings.get(key)
            holdings[key] = (
                replace(previous, quantity=previous.quantity + item.quantity)
                if previous else CollectionRow(item.card, item.quantity, category="regular")
            )
        intake_path = paths.locations / "intake" / f"{current.batch}.csv"
        receipt_path = paths.imports / "batches" / f"{current.batch}.csv"
        raw_destination = import_dir / "processed" / f"{current.batch}.csv"
        if raw_destination.exists():
            raise CollectionError(f"Processed scanner export already exists: {raw_destination}")
        intake_content = _location_bytes(current.cards)
        log = _read_log(paths)
        log.append({
            "batch": current.batch,
            "content_hash": current.content_hash,
            "source_file": source.name,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "card_versions": str(len(current.cards)),
            "copies": str(current.copies),
            "intake_hash": hashlib.sha256(intake_content).hexdigest(),
            "status": "active",
            "undone_at": "",
        })
        _commit_files(paths, {
            paths.holdings: _holding_bytes(holdings),
            intake_path: intake_content,
            receipt_path: _batch_bytes(current.cards),
            paths.imports / "log.csv": _log_bytes(log),
            raw_destination: source.read_bytes(),
            source: None,
        }, maximum_conflicts=collection_status(paths)["conflicts"])
    print(f"Imported {current.copies} card(s) into Intake/{current.batch}.")
    return True


def _read_receipt(path: Path) -> tuple[ImportCard, ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != BATCH_COLUMNS:
            raise CollectionError(f"{path}: unsupported batch receipt columns")
        cards = []
        for row in reader:
            cards.append(ImportCard(
                CardKey(row["card"], row["printing"], row["foil"]),
                row["finish"], int(row["quantity"]),
            ))
    return _canonical(cards)


def _undo_plan(paths: CollectionPaths, batch: str) -> tuple[dict[str, str], tuple[ImportCard, ...]]:
    check_import_transaction(paths)
    entries = [entry for entry in _read_log(paths) if entry["batch"] == batch]
    if len(entries) != 1 or entries[0]["status"] != "active":
        raise CollectionError(f"No active import named {batch!r}")
    entry = entries[0]
    receipt = paths.imports / "batches" / f"{batch}.csv"
    intake = paths.locations / "intake" / f"{batch}.csv"
    if not receipt.is_file() or not intake.is_file():
        raise CollectionError("Batch receipt or Intake location is missing; cannot undo automatically")
    cards = _read_receipt(receipt)
    if _fingerprint(cards) != entry["content_hash"]:
        raise CollectionError("Batch receipt changed; cannot undo automatically")
    if hashlib.sha256(intake.read_bytes()).hexdigest() != entry["intake_hash"]:
        raise CollectionError("Intake placement changed; cards may have moved, so undo is unsafe")
    holdings = _holdings_map(paths)
    amounts: dict[tuple[str, str, str], int] = defaultdict(int)
    for item in cards:
        amounts[item.card.normalized] += item.quantity
    for key, quantity in amounts.items():
        existing = holdings.get(key)
        if existing is None or existing.quantity < quantity:
            raise CollectionError(f"Not enough holdings remain to undo {key[0]}")
    return entry, cards


def undo_batch(
    paths: CollectionPaths,
    import_dir: Path,
    batch: str,
    *,
    preview: bool = False,
    confirm: Callable[[str], str] | None = input,
) -> bool:
    batch = _slug(batch)
    entry, cards = _undo_plan(paths, batch)
    print(f"Undo batch: {batch}")
    print(f"Copies to remove from holdings and Intake: {sum(item.quantity for item in cards)}")
    print("Recorded Intake placement has not changed since import.")
    if preview:
        return False
    if confirm is None or confirm("Undo this batch? [y/N] ").strip().casefold() not in {"y", "yes"}:
        print("Undo cancelled; no files changed.")
        return False
    with _import_lock(import_dir):
        current_entry, current_cards = _undo_plan(paths, batch)
        if current_entry != entry or current_cards != cards:
            raise CollectionError("Batch changed after preview; run undo again")
        holdings = _holdings_map(paths)
        amounts: dict[tuple[str, str, str], int] = defaultdict(int)
        for item in cards:
            amounts[item.card.normalized] += item.quantity
        for key, quantity in amounts.items():
            existing = holdings[key]
            remaining = existing.quantity - quantity
            if remaining:
                holdings[key] = replace(existing, quantity=remaining)
            else:
                del holdings[key]
        log = _read_log(paths)
        for row in log:
            if row["batch"] == batch:
                row["status"] = "undone"
                row["undone_at"] = datetime.now(timezone.utc).isoformat()
        _commit_files(paths, {
            paths.holdings: _holding_bytes(holdings),
            paths.locations / "intake" / f"{batch}.csv": None,
            paths.imports / "log.csv": _log_bytes(log),
        }, maximum_conflicts=collection_status(paths)["conflicts"])
    print(f"Undid batch {batch}; receipt and processed export were retained.")
    return True
