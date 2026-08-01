# Challenge32

Challenge32 is a project to maintain decent or competitive Commander decks for
each of Magic: The Gathering's 32 colour identities.

The deckbuilding source of truth is the deck-hosting service. Git records the
retrieved decklists, immutable snapshots, and analysis history.

## Current synchronizer

The first provider is Archidekt. Public deck pages are fetched at a low rate;
no login credentials are required. The synchronizer uses `mtg_parser` for the
deck/card parsing model and includes a compatibility layer for Archidekt's
current public page format.

Create or activate the recommended environment:

```bash
conda create -n challenge32 python=3.12 pip
conda activate challenge32
python -m pip install -e .
```

Each tracked deck has a `deck.toml` file:

```text
decks/
└── naya/
    └── omnislash/
        ├── deck.toml
        ├── current.txt
        ├── versions/
        ├── notes/
        ├── notes/status.md
        ├── state.json
        └── sync-log.md
```

Synchronize one deck:

```bash
challenge32-sync sync --deck decks/naya/omnislash
```

Synchronize all configured decks:

```bash
challenge32-sync sync --all
```

Preview a synchronization without writing files:

```bash
challenge32-sync sync --deck decks/naya/omnislash --dry-run
```

A new immutable version is created only when the normalized card list changes.
The generated `notes/status.md` reports whether the current deck hash has been
covered by an analysis note. Analysis notes should include front matter like:

```yaml
---
deck_version: 20260801T120000Z--abc1234
deck_hash: sha256:...
---
```

The synchronizer never rewrites analysis prose.

