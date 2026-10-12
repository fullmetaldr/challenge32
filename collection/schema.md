# Challenge32 collection data

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

## rarities.csv

This source-controlled lookup stores rarity for an exact printing, independent
of foil status or owned quantity. Populate missing entries explicitly with
`challenge32 collection rarity`. An absent entry means unknown rarity; `special`
and `bonus` are not automatically treated as rare or mythic.

```csv
card,printing,rarity
Sol Ring,cmm:396,uncommon
```

Deck allocation is derived from the tracked decklists and is never duplicated
in a manually maintained location file. The initial layout contains Reserve,
Unknown, ten named binders, colour-based Staging files, and one Maybe Box file
per deck. Each binder has its own file under `locations/binders/` and its own
digital location (for example `binder:white`). Empty binder files record no
cards; they do not imply that any cards have been physically filed there.
Every CSV under `locations/staging/`, including nested batch files, contributes to the
single Staging location in the database. Filenames and subdirectories organise
source data; they do not define additional locations. Batch imports create
`locations/staging/imported/<batch>.csv` for guarded undo.
`imports/batches/<batch>.csv` and `imports/log.csv` record applied imports and
allow guarded undo. The raw scanner export stays under ignored `data/imports/`.

The SQLite database is generated state. It is not a hand-edited source file.
