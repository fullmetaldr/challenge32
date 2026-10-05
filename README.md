# Challenge32

Challenge32 is a project to maintain decent or competitive Commander decks for
each of Magic: The Gathering's 32 colour identities.

The deckbuilding source of truth is the deck-hosting service. Git records the
retrieved decklists, immutable snapshots, and analysis history.

## Challenge progress

This table is generated from the tracked deck configurations. Run `challenge32 progress` to refresh it manually; `challenge32 add` refreshes it automatically after adding a deck.

| Colour identity | Status | Deck | Commander | Analysis |
|---|---|---|---|---|
| Colorless | Not started | — | — | — |
| White | Not started | — | — | — |
| Blue | Not started | — | — | — |
| Black | Tracked | [Top 0.1 percent](decks/black/top-0-1-percent/current.txt) ([source](https://archidekt.com/decks/26679986/top_01_percent)) | Ayara, First of Locthwain | Unreviewed |
| Red | Tracked | [I Smell Blood](decks/red/i-smell-blood/current.txt) ([source](https://archidekt.com/decks/24922183/i_smell_blood)) | Jaws, Relentless Predator | Unreviewed |
| Green | Not started | — | — | — |
| Azorius | Not started | — | — | — |
| Dimir | Tracked | [Milling on a Prayer](decks/dimir/milling-on-a-prayer/current.txt) ([source](https://archidekt.com/decks/26427794/milling_on_a_prayer)) | Haunted One<br>Zellix, Sanity Flayer | Unreviewed |
| Rakdos | Not started | — | — | — |
| Gruul | Not started | — | — | — |
| Selesnya | Tracked | [Angels Don't Scry](decks/selesnya/angels-don-t-scry/current.txt) ([source](https://archidekt.com/decks/27053327/angels_dont_scry)) | Trelasarra, Moon Dancer | Unreviewed |
| Orzhov | Tracked | [The Circle of Life](decks/orzhov/the-circle-of-life/current.txt) ([source](https://archidekt.com/decks/25209011/the_circle_of_life)) | Kambal, Profiteering Mayor | Unreviewed |
| Izzet | Tracked | [Sling it Like it's Hot](decks/izzet/sling-it-like-it-s-hot/current.txt) ([source](https://archidekt.com/decks/24921939/sling_it_like_its_hot)) | Ghyrson Starn, Kelermorph | Unreviewed |
| Golgari | Tracked | [APD](decks/golgari/apd/current.txt) ([source](https://archidekt.com/decks/24922346/apd)) | Chatterfang, Squirrel General | Unreviewed |
| Boros | Tracked | [Praise the Sun](decks/boros/praise-the-sun/current.txt) ([source](https://archidekt.com/decks/24888846/praise_the_sun)) | Otharri, Suns' Glory | Unreviewed |
| Simic | Not started | — | — | — |
| Esper | Not started | — | — | — |
| Grixis | Tracked | [Dream of Mirrors](decks/grixis/dream-of-mirrors/current.txt) ([source](https://archidekt.com/decks/25702223/dream_of_mirrors)) | Nekusar, the Mindrazer | Unreviewed |
| Jund | Not started | — | — | — |
| Naya | Tracked | [Omnislash](decks/naya/omnislash/current.txt) ([source](https://archidekt.com/decks/15661283/omnislash)) | Cloud, Ex-SOLDIER | Unreviewed |
| Bant | Tracked | [Kweh Kweh!](decks/bant/kweh-kweh/current.txt) ([source](https://archidekt.com/decks/24922076/kweh_kweh)) | Choco, Seeker of Paradise | Unreviewed |
| Abzan | Tracked | [Saga Frontier](decks/abzan/saga-frontier/current.txt) ([source](https://archidekt.com/decks/25034017/saga_frontier)) | Narci, Fable Singer | Unreviewed |
| Temur | Not started | — | — | — |
| Jeskai | Tracked | [The Will of the Gods](decks/jeskai/the-will-of-the-gods/current.txt) ([source](https://archidekt.com/decks/24888658/the_will_of_the_gods))<br>[Walk this plane!](decks/jeskai/walk-this-plane/current.txt) ([source](https://archidekt.com/decks/24884017/walk_this_plane)) | Atreus, Impulsive Son<br>Kratos, Stoic Father<br>Commodore Guff | Unreviewed<br>Unreviewed |
| Sultai | Not started | — | — | — |
| Mardu | Tracked | [Lightning Strikes Twice](decks/mardu/lightning-strikes-twice/current.txt) ([source](https://archidekt.com/decks/24889970/lightning_strikes_twice)) | Isshin, Two Heavens as One | Unreviewed |
| Yore-Tiller | Tracked | [It's Morphing time!](decks/yore-tiller/it-s-morphing-time/current.txt) ([source](https://archidekt.com/decks/27008458/its_morphing_time)) | Jace, Multiverse Architect | Unreviewed |
| Witch-Maw | Not started | — | — | — |
| Ink-Treader | Tracked | [All the Aragorns](decks/ink-treader/all-the-aragorns/current.txt) ([source](https://archidekt.com/decks/24890308/all_the_aragorns)) | Aragorn, the Uniter | Unreviewed |
| Dune-Brood | Not started | — | — | — |
| Glint-Eye | Not started | — | — | — |
| Five-color | Tracked | [Shrine Bright Like a Diamond](decks/five-color/shrine-bright-like-a-diamond/current.txt) ([source](https://archidekt.com/decks/24922005/shrine_bright_like_a_diamond))<br>[The Avatar Cycle](decks/five-color/the-avatar-cycle/current.txt) ([source](https://archidekt.com/decks/24884384/the_avatar_cycle)) | Go-Shintai of Life's Origin<br>Avatar Aang // Aang, Master of Elements | Unreviewed<br>Unreviewed |

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
challenge32 sync --deck decks/naya/omnislash
```

Synchronize all configured decks:

```bash
challenge32 sync --all
```

Add a new public Archidekt deck directly from its URL. The command fetches the
deck before writing anything, infers the deck name and Commander colour
identity, creates the correct directory and `deck.toml`, and performs the
initial synchronization:

```bash
challenge32 add https://archidekt.com/decks/<deck-id>/<deck-name>
```

Preview the inferred destination without writing files:

```bash
challenge32 add https://archidekt.com/decks/<deck-id>/<deck-name> --dry-run
```

Preview a synchronization without writing files:

```bash
challenge32 sync --deck decks/naya/omnislash --dry-run
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

## Dashboard

Build the static dashboard locally from the tracked deck directories:

```bash
challenge32 dashboard
python -m http.server 8000 --directory site
```

Then open `http://localhost:8000`. The dashboard is generated automatically for
GitHub Pages whenever the repository's `main` branch changes.

## Collection management

The collection model records only cards that have been explicitly encountered
or entered. It does not assume that an absent card is unowned. Deck allocation
is derived from the tracked decklists; non-deck locations will be represented
by source-controlled files under `collection/locations/`.

The first initialization is deliberately guarded and will create the schema,
empty location lists, initial holdings, and a derived SQLite database from the
current decklists:

```bash
challenge32 collection --init
```

Initialization requires two confirmations and refuses to overwrite an existing
collection. The derived database is stored in `.data/collection.sqlite` and is
ignored by Git. Once initialized, inspect the current model with:

```bash
challenge32 collection --status
```

Collection identities include the card name, a `printing` value such as
`cmm:396`, and `foil` (`yes`, `no`, or `unknown`). Categories such as `proxy`
are descriptive metadata and do not bypass quantity or allocation accounting.
