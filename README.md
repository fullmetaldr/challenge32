# Challenge32

Challenge32 is a project to maintain decent or competitive Commander decks for
each of Magic: The Gathering's 32 colour identities.

The deckbuilding source of truth is the deck-hosting service. Git records the
retrieved decklists, immutable snapshots, and analysis history.

## Challenge progress

This table is generated from the tracked deck configurations. Run `challenge32-sync progress` to refresh it manually; `challenge32-sync add` refreshes it automatically after adding a deck.

| Colour identity | Status | Deck | Commander | Analysis |
|---|---|---|---|---|
| Colorless | Not started | — | — | — |
| White | Not started | — | — | — |
| Blue | Not started | — | — | — |
| Black | Not started | — | — | — |
| Red | Not started | — | — | — |
| Green | Not started | — | — | — |
| Azorius | Not started | — | — | — |
| Dimir | Not started | — | — | — |
| Rakdos | Not started | — | — | — |
| Gruul | Not started | — | — | — |
| Selesnya | Not started | — | — | — |
| Orzhov | Not started | — | — | — |
| Izzet | Not started | — | — | — |
| Golgari | Not started | — | — | — |
| Boros | Not started | — | — | — |
| Simic | Not started | — | — | — |
| Esper | Not started | — | — | — |
| Grixis | Not started | — | — | — |
| Jund | Not started | — | — | — |
| Naya | Tracked | [Omnislash](decks/naya/omnislash/current.txt) ([source](https://archidekt.com/decks/15661283/omnislash)) | Cloud, Ex-SOLDIER | Unreviewed |
| Bant | Not started | — | — | — |
| Abzan | Not started | — | — | — |
| Temur | Not started | — | — | — |
| Jeskai | Tracked | [Walk this plane!](decks/jeskai/walk-this-plane/current.txt) ([source](https://archidekt.com/decks/24884017/walk_this_plane)) | Commodore Guff | Unreviewed |
| Sultai | Not started | — | — | — |
| Mardu | Not started | — | — | — |
| Yore-Tiller | Not started | — | — | — |
| Witch-Maw | Not started | — | — | — |
| Ink-Treader | Not started | — | — | — |
| Dune-Brood | Not started | — | — | — |
| Glint-Eye | Not started | — | — | — |
| Five-color | Tracked | [The Avatar Cycle](decks/five-color/the-avatar-cycle/current.txt) ([source](https://archidekt.com/decks/24884384/the_avatar_cycle)) | Avatar Aang // Aang, Master of Elements | Unreviewed |

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

Add a new public Archidekt deck directly from its URL. The command fetches the
deck before writing anything, infers the deck name and Commander colour
identity, creates the correct directory and `deck.toml`, and performs the
initial synchronization:

```bash
challenge32-sync add https://archidekt.com/decks/<deck-id>/<deck-name>
```

Preview the inferred destination without writing files:

```bash
challenge32-sync add https://archidekt.com/decks/<deck-id>/<deck-name> --dry-run
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
