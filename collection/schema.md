# Challenge32 collection data

The collection files are source-controlled and intentionally represent only
cards that have been explicitly encountered or recorded. An absent card is
not evidence that it is unowned.

## holdings.csv

`holdings.csv` records known owned quantities. `card` and `printing` identify a
card version; printing is stored as `set-code:collector-number` when available.
`foil` is `yes`, `no`, or `unknown`. `category` is descriptive metadata such as
`regular` or `proxy` and does not change quantity accounting. `rarity`,
`colour_identity`, and `type_line` describe the exact printing. Colour identity
uses WUBRG letters or `C` for colourless; an empty cell means unknown.

```csv
card,printing,foil,quantity,category,rarity,colour_identity,type_line,notes
Sol Ring,cmm:396,no,1,regular,uncommon,C,Artifact,
```

## locations/

Location files use the same identity columns, but omit `category`:

```csv
card,printing,foil,quantity,notes
Sol Ring,cmm:396,no,1,
```

The importer verifies new printings against Scryfall and fills their metadata
before committing a batch. Staging filing uses eight sections: the five
colours, Multicolour, Colourless, and Lands. The Land card type takes precedence
over colour identity. Preview with
`challenge32 collection file <section> --preview`, then, after physically filing
the entire section, run `challenge32 collection file <section>` to confirm its digital move. Rare and
mythic printings go to that section's binder; all other rarities go to Reserve.
Filing leaves holdings unchanged. If a source row came from an imported batch,
whole-batch undo becomes unavailable once that row is moved.

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
