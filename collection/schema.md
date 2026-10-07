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

Deck allocation is derived from the tracked decklists and is never duplicated
in a manually maintained location file. The initial layout contains Reserve,
Unknown, colour-based Staging sections, and one Maybe Box file per deck.
Batch imports create `locations/intake/<batch>.csv` until those cards are sorted.
`imports/batches/<batch>.csv` and `imports/log.csv` record applied imports and
allow guarded undo. The raw scanner export stays under ignored `data/imports/`.

The SQLite database is generated state. It is not a hand-edited source file.
