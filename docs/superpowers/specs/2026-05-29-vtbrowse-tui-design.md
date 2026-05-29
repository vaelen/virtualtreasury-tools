# vtbrowse — a TUI for `vtindex` + `vtextract`

Status: shipped on branch worktree-vtbrowse (commit history under docs/superpowers/plans/2026-05-29-vtbrowse.md).

Status: design, agreed in brainstorm 2026-05-29.

## What this is

A terminal GUI built with [Textual](https://textual.textualize.io/) that sits
on top of an existing `vtextract` archive and its `vtindex` index. The user
browses volumes, drills into pages, searches across the index, curates a
**bundle** of pages they care about, and exports that bundle (transcriptions
+ per-page metadata + optional images) to a folder or compressed archive for
sharing with other applications.

It is read-only with respect to the archive store on disk. It calls out to
the existing `vtextract` CLI when the user opts into images during export
(to backfill anything missing); otherwise it talks to the archive and the
SQLite index through the same Python modules `vtindex` already uses.

## Why Textual

The existing CLI already renders with `rich` (`Console`, `Table`, themes).
Textual builds on `rich`, so the same styling primitives carry over and we
get keyboard-driven navigation, focus, modal dialogs, and async I/O without
a custom event loop. App name: **`vtbrowse`**.

## Architectural boundaries

`vtbrowse` is deliberately constrained in how it touches the data.

**Owns** — TUI rendering, the selection model, bundle JSON load/save,
export folder/zip writing.

**Shells out to `vtindex`** (subprocess, JSON output) for **every**
interaction with the index database. `vtbrowse` never opens
`archive/index/vtindex.sqlite3` itself — keeping the SQL schema and FTS5
contract sealed inside `vtindex`. Uses:

- `vtindex volumes --json` — volume list (screen 1)
- `vtindex search --json …` — keyword search (screens 4–6)
- `vtindex page <root>/<key> --json` — prev/next neighbour for the
  transcription viewer (screen 3)
- `vtindex stats --json` — initial staleness check (screen 12) and
  in-session re-check that backs the stale chip (screen 14)
- `vtindex build` — startup rebuild prompt and `⌃B` (screens 12, 13)
- *(new, see "Required additions" below)* `vtindex pages <root> --json`
  for the per-volume page list (screen 2) and `vtindex item <id> --json`
  for the Info dialog (screen 9)

**Shells out to `vtextract`** (subprocess) for:

- `vtextract search …` — Step 1 of `⌃E` (screen 15b)
- `vtextract get --refresh --images <isadg_ids>` — image backfill at
  Export time (screen 7)

**Reads directly from the archive on disk** for content the index doesn't
hold:

- per-page transcription `archive/pages/<root>/<page_key>.txt`
- per-page metadata     `archive/pages/<root>/<page_key>.json`
- per-page image        `archive/pages/<root>/<page_key>` (existence check
  for the `Img` column; bytes only consulted by the export step)
- per-volume snapshot   `archive/pages/<root>/volume.json` (for the
  Export folder's `volume.json` copy)

This split means a `vtindex` schema change is invisible to `vtbrowse` as
long as the CLI's JSON contract holds, and the file-tree layout under
`archive/` (already part of the public design spec) is the only other
surface `vtbrowse` couples to.

## Out of scope (deferred)

- Editing/rewriting transcriptions or metadata.
- `vtextract get` from inside the TUI. (Images during export are the one
  exception — fetched on demand via `vtextract get --refresh --images`.)
- Multi-clause `vtextract search` from inside the TUI. The in-app extract
  dialog (`⌃E`) supports a single clause only; the CLI remains the place
  to build complex multi-clause searches.
- Mouse interactions. Keyboard only.

## Layout

The screen is two panes side by side, with a one-line header above and a
one-line footer below — both spanning the full width.

```
 vtbrowse — <context line>                                <right-aligned counter>
┌─ Bundle ──────────┐┌─ <document-pane title> ──────────────────────────────────────────┐
│                   ││                                                                  │
│                   ││                                                                  │
│   (content)       ││   (content)                                                      │
│                   ││                                                                  │
│                   ││                                                                  │
└───────────────────┘└──────────────────────────────────────────────────────────────────┘
 <context-relevant key hints>
```

- **Bundle pane** (left, fixed ~20 cols): the user's curated set of pages,
  grouped by volume. Only volumes that have selected pages appear. Empty
  state shows `(no selections)`.
- **Document pane** (right, ~80%): everything else — volume list, page
  list, transcription, search results. The pane's title changes with
  context (`Volumes`, `<Volume title> (<root_id>)`, `<Volume title> —
  p.<N> — <page_key>`, `Search results`).
- **Header**: app name, current context, right-aligned counter (e.g.
  `247 volumes`, `9 pages`, `27 results`).
- **Footer**: context-aware shortcut hints. A full key map lives on `F1` /
  `?` help.

Focus moves between panes with `tab`. The focused pane shows a `▸` cursor
on the active row.

### Modal dialogs (overlays)

Search, Save bundle, Open bundle, Export bundle, Info, Exit confirm.
All centred over the document pane; `esc` cancels, `tab` cycles fields,
`⏎` submits the default button.

## Screens

### 1. Volumes (home)

```
 vtbrowse — Virtual Record Treasury browser                                   247 volumes
┌─ Bundle ──────────┐┌─ Volumes ──────────────────────────────────────────────────────────┐
│ (no selections)   ││   Root ID    Items   Title                                Reference │
│                   ││  ────────  ──────── ────────────────────────────────── ──────────── │
│                   ││   0001          42   Calendar of Patent Rolls            IRE/PR/01  │
│                   ││   0002          17   State Papers Ireland 1641           SPI/1641   │
│                   ││  ▸0007           9   Council Book of Dublin              CB/DUB/164 │
│                   ││  ...                                                                │
│                   ││  row 7 of 247                                                       │
└───────────────────┘└────────────────────────────────────────────────────────────────────┘
 ↑↓ move   ⏎ open volume   ⌃F search   ⌃O open bundle   ⌃S save   ⌃I info   ⌃X exit
```

Columns mirror `vtindex volumes`: Root ID, Items, Title, Reference. Data
source: `IndexDB.volumes()`.

### 2. Page list (inside a volume)

```
 vtbrowse — Council Book of Dublin (0007)                                       9 pages
┌─ Bundle ──────────┐┌─ Council Book of Dublin (0007) ─ CB/DUB/1640 ─────────────────────┐
│ (no selections)   ││   #   Page key                              Txt   Img   Sel       │
│                   ││ ─── ───────────────────────────────────── ───── ───── ─────       │
│                   ││    1  cb_dub_001.jpg                        ·     ·               │
│                   ││    2  cb_dub_002.jpg                        ·     ·     *         │
│                   ││ ▸  4  cb_dub_004.jpg                        ·     ·               │
│                   ││  ...                                                              │
│                   ││ page 4 of 9                                                       │
└───────────────────┘└───────────────────────────────────────────────────────────────────┘
 ↑↓ move   ⏎ view   space select   esc back   ⌃F search   ⌃I info   ⌃X exit
```

Rows: ordinal, page key (Loris image filename), `Txt`/`Img` markers from
on-disk file presence (`.txt`, image), `Sel = *` if the page is in the
effective bundle. `space` toggles the page's user state (see selection
model below). Data source: `IndexDB` page iteration for the volume.

### 3. Transcription view

```
 vtbrowse — Council Book of Dublin — p.4                                page 4 of 9
┌─ Bundle (4) ──────┐┌─ Council Book of Dublin — p.4 — cb_dub_004.jpg ─[in bundle]──────┐
│ ▾ 0007 Council Bo ││ At the assemblie holden in the Tholsell of the said citie        │
│   p.2  cb_dub_002 ││ uppon Friday the second day of November in the yeare of our      │
│ ▸ p.4  cb_dub_004 ││ Lord God 1640, and in the sixteenth yeare of the raigne of       │
│ ▾ 0001 Calendar.. ││ our soveraigne Lord Charles by the grace of God of England,      │
│   p.13 pr_1605_01 ││ Scotland, France and Ireland King, Defender of the Faith.        │
│   p.14 pr_1605_01 ││ ...                                                              │
│                   ││ lines 1–14 of 87                                                 │
└───────────────────┘└──────────────────────────────────────────────────────────────────┘
 ←→ prev/next page   ↑↓ scroll   space deselect   esc back   tab → Bundle   ⌃I info
```

Transcription is the contents of `archive/pages/{root_id}/{page_key}.txt`
word-wrapped to the pane width. `←` / `→` move to the previous/next page
in the *volume* by ordinal (using `IndexDB.page_at_ordinal`). `[in bundle]`
in the title reflects the page's effective state. `tab` swaps focus to the
Bundle pane.

### 4. Search dialog (`⌃F`)

```
┌────────────────────── Search ─────────────────────────────┐
│                                                           │
│  Query       [ pirate Dublin                          ]   │
│  Search in   [x] Title   [x] Description  [x] Transcr.    │
│  Date type   (•) Content     ( ) Created                  │
│  From        [ 1640      ]  To  [ 1660    ]               │
│  Volume      [                                        ]   │
│  Limit       [   50 ]                                     │
│                                                           │
│              [ Search ]   [ Cancel ]                      │
└───────────────────────────────────────────────────────────┘
```

Fields map 1:1 to `vtindex search` flags. If invoked from inside a volume
or from a search-results-derived page, **Volume** pre-fills with that
volume's root id; clearing it widens to all volumes.

### 5. Search results

```
 vtbrowse — Search: "pirate Dublin" 1640–1660 content                27 results
┌─ Bundle (7) ──────┐┌─ Search results ──────────────────────────────────────────────────┐
│ ▾ 0007 Council Bo ││  Sel   ID      Date     Est.    Reference         Title          │
│   p.4  cb_dub_004 ││ ───── ──────  ────────  ──────  ────────────────  ─────────────  │
│   p.5  cb_dub_005 ││  [x]   18421  1641-03    —       CB/DUB/164.1      Petition conc.│
│   p.6  cb_dub_006 ││ ▸[x]   18425  1641-05    —       CB/DUB/164.5      Pirate sightin│
│ ▾ 0001 Calendar.. ││  [ ]   18532    —        1644    APC/IRE/01.7      Letter re Dub.│
│   p.13 pr_1605_01 ││  [x]   19014  1647-09    —       PR/HEN/3.18       Pirate prize .│
│   p.14 pr_1605_01 ││  ...                                                              │
│                   ││ result 2 of 27   matches: title + transcription   pages: 3        │
└───────────────────┘└───────────────────────────────────────────────────────────────────┘
 ↑↓ move   space toggle item   ⏎ view first match   ⌃F refine   esc clear   ⌃R results
```

- `space` on a row toggles the **item** in/out of the *selected items* set
  (see selection model below). The `[x]` checkbox column reflects that.
- `⏎` opens the item's primary matched page in the transcription view.
  From there, `←`/`→` move between physical pages in the volume (not
  between search matches).
- `esc` returns to the volumes screen but does **not** discard the
  results; `⌃R` re-opens them. They are only discarded when a new search
  is executed.

### 6. Transcription with search highlights

```
 vtbrowse — Council Book of Dublin — p.5     match 2 of 27          page 5 of 9
┌─ Bundle (4) ──────┐┌─ Council Book of Dublin — p.5 — cb_dub_005.jpg ──────────────────┐
│ ▾ 0007 Council Bo ││ Whereas there hath beene divers complaints made unto this        │
│   p.2  cb_dub_002 ││ assembly touching the depredations committed by certaine         │
│ ▸ p.4  cb_dub_004 ││ «pirate»s lurking aboute the porte of «Dublin» and along the     │
│ ▾ 0001 Calendar.. ││ coastes of Leinster, to the great damage of the marchants of     │
│   p.13 pr_1605_01 ││ this citie...                                                    │
│   p.14 pr_1605_01 ││ It is therefore agreed that a watch be sett upon the harbour     │
│                   ││ to give warninge of any such «pirate» vessels approachinge from  │
│                   ││ the seaward, that the citizens may be in readinesse...           │
│                   ││ lines 1–14 of 62   3 hits on this page                           │
└───────────────────┘└──────────────────────────────────────────────────────────────────┘
 ←→ prev/next page   ↑↓ scroll   space select   esc back to results   ⌃I info
```

When opened from a search, the page viewer remembers the active query and
highlights matches using the same rich `match_style` `vtindex search`
already uses for title highlights. The header's `match N of M` annotation
only appears when the current page is itself in the result set; if the
user `←`/`→`s onto an off-result neighbour, only `page X of Y` shows.
`esc` returns to the search results list.

### 7. Export dialog (`⌃⇧S`)

```
┌─────────────────────────── Export bundle ─────────────────────────────────┐
│                                                                           │
│  Location  /Users/andrew/Documents/research                          [..] │
│  ───────────────────────────────────────────────────────────────────────  │
│    ../                                                                    │
│    papers/                                                                │
│  ▸ vt-exports/                                                            │
│    notes.md                                                               │
│    bundle_20260415_104530.zip                                             │
│                                                                           │
│  Name      [ bundle_20260529_184523                                   ]   │
│  Format    (•) Folder   ( ) .zip   ( ) .tar.gz                            │
│  Include   [ ] Images (downloads any missing via vtextract --images)      │
│                                                                           │
│            [ Export ]   [ Cancel ]                                        │
└───────────────────────────────────────────────────────────────────────────┘
```

When `Include Images` is on and any selected page lacks its image on disk,
the TUI shells out to `vtextract get --refresh --images <isadg_ids>` for
the items contributing those pages before writing the bundle. Progress is
reported in a modal progress dialog reusing `BuildReporter`-style line
counters. If the user cancels mid-fetch, the dialog falls back to
"Continue without missing images / Cancel export".

### 8. Save dialog (`⌃S`)

```
┌──────────────────────────── Save bundle ──────────────────────────────────┐
│                                                                           │
│  Location  /Users/andrew/Documents/research                          [..] │
│  ───────────────────────────────────────────────────────────────────────  │
│    ../                                                                    │
│  ▸ vt-bundles/                                                            │
│    notes.md                                                               │
│    bundle_20260415_104530.json                                            │
│    bundle_20260520_191204.json                                            │
│                                                                           │
│  Name      [ bundle_20260529_184523                              ].json   │
│                                                                           │
│            [ Save ]   [ Cancel ]                                          │
└───────────────────────────────────────────────────────────────────────────┘
```

Default file name: `bundle_yyyymmdd_hhmmss.json` (local time). If the
typed name already exists at the chosen location, the dialog asks
`Overwrite "<name>.json"? [y/N]` inline above the buttons.

### 8b. Open dialog (`⌃O`)

```
┌──────────────────────────── Open bundle ──────────────────────────────────┐
│                                                                           │
│  Location  /Users/andrew/Documents/research/vt-bundles                [..]│
│  ───────────────────────────────────────────────────────────────────────  │
│    ../                                                                    │
│    bundle_20260301_093045.json     2 items, 7 pages                       │
│    bundle_20260415_104530.json     5 items, 14 pages                      │
│  ▸ bundle_20260520_191204.json    11 items, 31 pages                      │
│                                                                           │
│  Loading replaces the current Bundle (7 pages). Continue?                 │
│                                                                           │
│            [ Open ]   [ Cancel ]                                          │
└───────────────────────────────────────────────────────────────────────────┘
```

Filtered to `*.json`. The right-hand summary peeks `selected_items` and
`page_state` counts on focus. The "Loading replaces..." confirm line only
appears when the current bundle is non-empty and has unsaved changes.

### 9. Info dialog (`⌃I`)

Content depends on focus context.

**Page info** (focus is on a page row, transcription view, or a
search-result row that's been opened):

```
┌─────────────────────────── Page info ─────────────────────────────────────┐
│                                                                           │
│  Volume        0007 — Council Book of Dublin (CB/DUB/1640)                │
│  Page          p.5 of 9   cb_dub_005.jpg                                  │
│  In bundle     yes                                                        │
│  User state    default                                                    │
│                                                                           │
│  Contributing items                                                       │
│   ✓ 18421  Petition concerning pirate raids        (selected)             │
│   ✓ 18425  Pirate sightings off Dublin             (selected)             │
│                                                                           │
│  Records on this page                                                     │
│   • 18421  Petition concerning pirate raids        1641-03                │
│   • 18425  Pirate sightings off Dublin             1641-05                │
│   • 18437  Petition of merchants re shipping loss  1641-05                │
│                                                                           │
│  Files on disk                                                            │
│   image  archive/pages/0007/cb_dub_005.jpg                                │
│   text   archive/pages/0007/cb_dub_005.jpg.txt                            │
│   meta   archive/pages/0007/cb_dub_005.jpg.json                           │
│                                                                           │
│            [ Close ]                                                      │
└───────────────────────────────────────────────────────────────────────────┘
```

A page with an explicit user toggle would show `User state    exclude`
(or `include`) and the `In bundle` line would reflect the override.

**Volume info** (focus is on a volume row):

```
┌─────────────────────────── Volume info ───────────────────────────────────┐
│                                                                           │
│  Root ID       0007                                                       │
│  Title         Council Book of Dublin                                     │
│  Reference     CB/DUB/1640                                                │
│  Label         CB/DUB/1640                                                │
│  Items         9                                                          │
│  Pages indexed 9                                                          │
│  In bundle     2 pages from this volume                                   │
│                                                                           │
│            [ Close ]                                                      │
└───────────────────────────────────────────────────────────────────────────┘
```

**Item info** (focus is on a search-result row):

```
┌─────────────────────────── Item info ─────────────────────────────────────┐
│                                                                           │
│  ISADG ID      18425                                                      │
│  Title         Pirate sightings off Dublin                                │
│  Reference     CB/DUB/164.5                                               │
│  Repository    Dublin City Archives                                       │
│  Content date  1641-05                                                    │
│  Estimated     —                                                          │
│  Volume        0007 — Council Book of Dublin                              │
│  Matched in    title + transcription                                      │
│                                                                           │
│  Matched pages (3)                                                        │
│   • p.4  cb_dub_004.jpg                                                   │
│   • p.5  cb_dub_005.jpg   ← primary match                                 │
│   • p.6  cb_dub_006.jpg                                                   │
│                                                                           │
│  In bundle     yes (item selected)                                        │
│                                                                           │
│            [ Close ]                                                      │
└───────────────────────────────────────────────────────────────────────────┘
```

### 10. Exit confirm (`⌃X`)

```
┌──────────────── Exit vtbrowse ────────────────┐
│                                               │
│  Bundle has 7 pages from 3 items.             │
│  Unsaved changes will be lost.                │
│                                               │
│      [ Save & exit ]  [ Exit ]  [ Cancel ]    │
└───────────────────────────────────────────────┘
```

If the bundle is empty or unchanged since last save, exit is silent (no
dialog). `Save & exit` opens the Save dialog first; `Exit` quits
immediately; `Cancel` dismisses.

### 11. Bundle pane focused

```
 vtbrowse — Council Book of Dublin — p.5                              page 5 of 9
┌─ Bundle (7) ──────┐┌─ Council Book of Dublin — p.5 — cb_dub_005.jpg ──────────────────┐
│ ▾ 0007 Council Bo ││ Whereas there hath beene divers complaints made unto this        │
│   p.4  cb_dub_004 ││ assembly touching the depredations committed by certaine         │
│ ▸ p.5  cb_dub_005 ││ pirates lurking aboute the porte of Dublin and along the         │
│   p.6  cb_dub_006 ││ coastes of Leinster, to the great damage of the marchants of     │
│ ▾ 0001 Calendar.. ││ this citie...                                                    │
│   p.13 pr_1605_01 ││ ...                                                              │
│   p.14 pr_1605_01 ││ lines 1–14 of 62                                                 │
└───────────────────┘└──────────────────────────────────────────────────────────────────┘
 ↑↓ move   ⏎ jump to page   space remove   ← collapse vol   tab → Document   ⌃X exit
```

When focus is on the Bundle pane:
- `↑` / `↓` move between rows (volume headers and pages).
- `←` / `→` collapse / expand a volume node.
- `⏎` on a page jumps the document pane to that page's transcription
  view; `esc` from there returns to whatever the document pane was
  showing before (volume page list or search results).
- `space` removes the focused page (or all pages of a focused volume) by
  setting `state = exclude` on each.

### 12. Startup index prompt (missing or stale)

Shown once, immediately after the splash, when either:
- `vtindex` DB at `<archive>/.../index.db` is missing, or
- `is_stale(db, archive)` is true at startup.

```
┌────────────────────────────── vtbrowse ──────────────────────────────┐
│                                                                      │
│  The search index for this archive is out of date.                   │
│                                                                      │
│  Archive    /Users/andrew/repos/virtualtreasury-extractor/archive    │
│  Index      .../index/vtindex.sqlite3                                │
│                                                                      │
│  Rebuild it now? (recommended)                                       │
│                                                                      │
│            [ Yes (default) ]   [ No ]                                │
└──────────────────────────────────────────────────────────────────────┘
```

Missing-index variant swaps the first line to
`No search index exists for this archive yet.` and the question to
`Build it now? (recommended)`.

`⏎` accepts the default (`Yes`), launching the build modal (screen 13).
`No` / `esc` dismisses and either lands on the home screen with the
stale banner (screen 15) or — when the index doesn't exist at all — on
the no-index screen (screen 16).

### 13. Build progress modal (`⌃B`, or from screen 12)

```
┌────────────────────── vtindex build ──────────────────────────────────┐
│                                                                       │
│  Running: vtindex build --archive /…/archive                          │
│                                                                       │
│  ────────────────────────────────────────────────────────────────     │
│  scanning items…   1842 / 2,901                                       │
│  indexed:    + 412 new      ~  87 updated   = 1,343 unchanged         │
│  pages:      + 1,127        ~  214          = 4,098                   │
│  skipped:    3                                                        │
│  elapsed:    00:14                                                    │
│                                                                       │
│  ────────────────────────────────────────────────────────────────     │
│  scanning items/0007/18425…                                           │
│                                                                       │
│            [ Cancel ]                                                 │
└───────────────────────────────────────────────────────────────────────┘
```

Spawns `vtindex build --json-progress` as an `asyncio.subprocess`
child, reads stdout line-by-line and dispatches the JSON events
(see F4) into the modal's log line and counter block. On completion
the modal switches its button to `[ Close ]` and the title to
`vtindex build — done` (or `failed`). `Cancel` confirms once
(`Stop the build? in-progress writes will be rolled back`) before
sending `SIGTERM` to the child.

### 14. Stale-index banner (in-session)

```
 vtbrowse — Virtual Record Treasury browser     [stale: press ⌃B to rebuild]  247 volumes
┌─ Bundle ──────────┐┌─ Volumes ──────────────────────────────────────────────────────────┐
│ (no selections)   ││   Root ID    Items   Title                                Reference │
                    ...
```

A right-side chip in the header whenever `is_stale(db, archive)`
becomes true *during* a session (archive files changed under us).
Does not auto-rebuild and does not show a modal — the user presses
`⌃B` if and when they want to rebuild. Staleness *at startup* is
handled by screen 12, not this banner.

### 15. Extract dialog (`⌃E`)

A single-clause front end for `vtextract search`. The CLI supports
multi-clause searches by repeating field+operand+keywords; this dialog
deliberately exposes only one clause to keep the UI simple. For complex
queries the user drops to the CLI.

```
┌──────────────────── Extract from Virtual Treasury (⌃E) ──────────────────┐
│                                                                          │
│  Keywords    [ pirate Dublin                                         ]   │
│                                                                          │
│  Match       (•) all      ( ) any      ( ) exact                         │
│                                                                          │
│  Field       (•) keyword (all fields)    ( ) title    ( ) transcription  │
│              ( ) creator            ( ) reference     ( ) person         │
│              ( ) place                                                   │
│                                                                          │
│  From        [ 1640-01-01 ]    To    [ 1660-12-31 ]                      │
│                                                                          │
│  Will run: vtextract search --all pirate Dublin                          │
│            --start 1640-01-01 --end 1660-12-31                           │
│                                                                          │
│            [ Extract ]   [ Cancel ]                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

Behaviour:

- Match excludes `none` — it's meaningful only when combined with other
  clauses (`A AND NOT B`).
- Field default is `keyword (all fields)`, which maps to the CLI's bare
  `--keyword` flag (`kwSearchFieldList = "all"`).
- Fields map to CLI flags exactly as documented in
  `docs/search-query.md` (`title`, `transcription` → `--transcription`,
  `creator`, `reference` → `--ref`, `person`, `place`).
- Dates are optional (`--start` / `--end` only emitted when set).
- The "Will run:" preview live-updates as the form changes — same
  command we'll exec.
- Submitted runs **never** pass `--images`; image backfill stays an
  explicit choice at Export time.
- Other defaults stay implicit: `--out` = archive from config,
  `--context-pages 1`, `--relevance` sort, no `--refresh`.

### 15b. Extract + build progress modal

Opens when the user submits screen 15. Runs `vtextract search` to
completion, then automatically chains into `vtindex build` in the same
modal so the new content is immediately searchable.

```
┌────────────────── vtextract search → vtindex build ───────────────────┐
│                                                                       │
│  Step 1/2: vtextract search --all pirate Dublin                       │
│            --start 1640-01-01 --end 1660-12-31                        │
│                                                                       │
│  ────────────────────────────────────────────────────────────────     │
│  searching…    page 3 / 12                                            │
│  fetched:      47 items                                               │
│  new:          12   updated: 5    skipped: 30                         │
│  pages:        128 transcriptions   42 manifests                      │
│  elapsed:      00:32                                                  │
│                                                                       │
│  ────────────────────────────────────────────────────────────────     │
│  fetching items/0007/18472…                                           │
│                                                                       │
│            [ Cancel ]                                                 │
└───────────────────────────────────────────────────────────────────────┘
```

After search finishes the title's step indicator flips and the build
log starts streaming:

```
┌────────────────── vtextract search → vtindex build ───────────────────┐
│                                                                       │
│  Step 1/2: vtextract search ... (done — 47 items, 128 pages)          │
│  Step 2/2: vtindex build --archive /…/archive                         │
│                                                                       │
│  ────────────────────────────────────────────────────────────────     │
│  scanning items…   2,948 / 2,948                                      │
│  indexed:    + 47 new       ~  5 updated    = 2,896 unchanged         │
│  pages:      + 128          ~  0            = 4,212                   │
│  elapsed:    00:08                                                    │
│                                                                       │
│            [ Close ]                                                  │
└───────────────────────────────────────────────────────────────────────┘
```

Cancel behaviour:

- During Step 1: signals the search transport to stop on the next
  request boundary. Already-fetched items remain in the archive.
  Step 2 is **not** auto-started — the user can press `⌃B` later
  when they want.
- During Step 2: same as the `⌃B` build modal — confirms once, then
  signals the builder.

Error behaviour: if Step 1 raises (auth, network, transport), the
modal switches its title to `vtextract search — failed`, shows the
exception, and offers `[ Close ]`. Step 2 is **not** auto-started in
that case either.

Both steps run as `asyncio.subprocess` children of the TUI
(`vtextract search --json-progress` then `vtindex build
--json-progress`), with stdout drained line-by-line into the modal.
Cancel sends `SIGTERM` to the active child. This keeps `vtbrowse` on
the CLI-contract side of the architectural boundary — no in-process
import of the fetcher or the builder.

### 16. Empty-archive / no-index screen

Shown when the archive has no `vtindex` DB and the user declined the
startup prompt (screen 12), or when the configured archive doesn't look
like a `vtextract` archive at all.

```
 vtbrowse — no archive index found
┌─ Bundle ──────────┐┌─ Volumes ──────────────────────────────────────────────────────────┐
│ (no selections)   ││                                                                    │
│                   ││  No index found at /Users/andrew/.../archive/index/vtindex.sqlite3 │
│                   ││                                                                    │
│                   ││  Press ⌃B to build the index for the current archive.              │
│                   ││                                                                    │
│                   ││  Or relaunch with --config <path> to point at a different          │
│                   ││  vt.toml whose top-level `archive` key points elsewhere.           │
│                   ││                                                                    │
└───────────────────┘└────────────────────────────────────────────────────────────────────┘
 ⌃B build   ⌃X exit
```

## Selection model

The Bundle keeps three things separately. The effective bundle is derived
from them.

```
selected_items   : { isadg_id → {matched_pages: [page_ref, ...]} }
page_state       : { page_ref → "include" | "exclude" }
```

- `page_ref` = `(root_id, page_key)`.
- `matched_pages` is **snapshotted at selection time** so re-running the
  search later doesn't quietly change what's in the bundle.
- A page with no `page_state` entry is in the "default" state.

**Effective bundle**:

```
in_bundle(page) = (page ∈ ⋃ selected_items[*].matched_pages
                   OR page_state[page] == "include")
                 AND page_state[page] != "exclude"
```

### Toggle semantics

| Action | Effect |
|---|---|
| `space` on a search-result row | toggle that item in/out of `selected_items` |
| `space` on a page that **is** in the bundle | set `page_state[page] = "exclude"` |
| `space` on a page that **is not** in the bundle | set `page_state[page] = "include"` |

A `page_state` entry is **sticky**: it survives deselection and re-selection
of any contributing item. The user can clear it by toggling `space` again,
which flips it to the other explicit state, or by clearing it from the
Info dialog (`[ Clear override ]` button when state is not `default`).

### Why three components, not a flat page set

Two adjacent items in a volume often share context pages (the `vtindex`
search already returns up to 3 pages per match: the matched page plus
optional context pages before/after). With a flat page set, deselecting
one item would clobber pages still wanted by another item.

Tracking selected *items* lets us correctly reference-count those shared
pages. Tracking explicit `include`/`exclude` per page lets the user drill
in and override the default for any single page (e.g. drop an irrelevant
context page from an otherwise-wanted item) without losing the override
across item churn.

## Bundle file format (`⌃S` / `⌃O`)

JSON, one file per saved bundle. The schema mirrors the in-memory state:

```json
{
  "version": 1,
  "created_at": "2026-05-29T18:45:23Z",
  "selected_items": [
    {
      "isadg_id": 18425,
      "matched_pages": [
        {"root_id": "0007", "page_key": "cb_dub_004.jpg"},
        {"root_id": "0007", "page_key": "cb_dub_005.jpg"},
        {"root_id": "0007", "page_key": "cb_dub_006.jpg"}
      ]
    }
  ],
  "page_state": [
    {"root_id": "0007", "page_key": "cb_dub_009.jpg", "state": "include"},
    {"root_id": "0007", "page_key": "cb_dub_005.jpg", "state": "exclude"}
  ]
}
```

Default filename: `bundle_yyyymmdd_hhmmss.json` (local time). On `⌃O`,
unknown `version` values are rejected with a dialog explaining the
mismatch.

## Export layout

Default folder name: `bundle_yyyymmdd_hhmmss/` (or `.zip` / `.tar.gz` if a
compressed format is chosen).

```
bundle_20260529_184523/
  0007/                          # volume root id
    volume.json                  # snapshot of IndexDB.volume(root_id)
    cb_dub_004.jpg.json          # per-page metadata (copy of archive page meta)
    cb_dub_004.jpg.txt           # transcription
    cb_dub_004.jpg               # image (only if --images was chosen)
    cb_dub_005.jpg.json
    cb_dub_005.jpg.txt
    cb_dub_005.jpg
  0001/
    volume.json
    pr_1605_013.jpg.json
    pr_1605_013.jpg.txt
  bundle.json                    # the same JSON ⌃S writes, copied in
```

`bundle.json` at the top lets the receiver re-open the export folder in
`vtbrowse` later without losing the item/state structure.

## Keyboard shortcuts

| Key | Context | Action |
|---|---|---|
| `↑` / `↓` | any list | move row cursor |
| `←` / `→` | transcription view | previous / next page in volume |
| `←` / `→` | Bundle pane | collapse / expand volume node |
| `⏎` | volume row | open page list |
| `⏎` | page row | open transcription |
| `⏎` | search-result row | open first matched page |
| `⏎` | Bundle page row | jump document pane to that page |
| `space` | page row, transcription view | toggle page user state |
| `space` | search-result row | toggle item in `selected_items` |
| `space` | Bundle row | remove page (or volume's pages) |
| `esc` | any | back one level (transcription → list → home; results → home) |
| `tab` | any | swap focus between Bundle and Document panes |
| `⌃F` | any | open Search dialog |
| `⌃O` | any | Open bundle |
| `⌃S` | any | Save bundle |
| `⌃⇧S` | any | Export bundle |
| `⌃I` | any | Info on focused context |
| `⌃V` | any | jump to Volumes |
| `⌃R` | any | jump to last search results |
| `⌃X` | any | Exit (confirm if unsaved) |
| `⌃B` | any | Build / rebuild the `vtindex` index (modal progress) |
| `⌃E` | any | Extract from Virtual Treasury (single-clause `vtextract search`, then auto-build) |
| `F1` / `?` | any | full key map |

## Module sketch

Under `src/vtextract/tui/`:

- `app.py` — the Textual `App` subclass and global keymap.
- `panes/bundle.py`, `panes/document.py` — the two persistent panes.
- `screens/volumes.py`, `screens/pages.py`, `screens/transcription.py`,
  `screens/results.py` — document-pane content widgets.
- `dialogs/search.py`, `dialogs/file.py`, `dialogs/info.py`,
  `dialogs/exit.py`, `dialogs/build.py`, `dialogs/extract.py` —
  modal screens. `dialogs/extract.py` owns both the form (15) and the
  chained progress modal (15b); the build modal (13) is the same widget
  used by `⌃B` alone with Step 1 elided.
- `bundle.py` — the selection model (in-memory `Bundle` dataclass with
  `selected_items`, `page_state`, and `effective_pages()` /
  `is_in_bundle(page)` derivations) plus JSON load/save.
- `index_client.py` — the **single** subprocess choke point for
  `vtindex` (analogous to `vtextract.client` for HTTP). Owns
  `volumes()`, `search()`, `page()`, `pages()`, `item()`, `stats()`,
  and `build()` (the last as an async generator yielding progress
  events). Every other module that wants index data goes through here.
- `extract_client.py` — same idea for `vtextract`: `search(...)` (Step
  1 of `⌃E`) and `get_images(isadg_ids)` (Export image backfill).
  Async generators that yield JSON progress events.
- `archive_reader.py` — direct on-disk reads of transcription
  (`<page_key>.txt`), per-page metadata (`<page_key>.json`), per-volume
  snapshot (`volume.json`), and per-item identity. No HTTP, no SQL.
- `export.py` — write `bundle_*` folders / archives by combining
  `archive_reader` with the on-disk pages, calling `extract_client`
  when image backfill is needed.

`vtbrowse` does **not** import from `vtextract.index.db`,
`vtextract.index.query`, `vtextract.index.builder`,
`vtextract.fetcher`, or `vtextract.client`. The `vtindex` / `vtextract`
subprocess CLI is the only contract.

Tests:
- `bundle.py` — pure unit tests covering all the toggle and corner-case
  rules from the selection model.
- `index_client.py` / `extract_client.py` — driven against a fake
  subprocess (`subprocess.run` monkeypatched) that returns canned JSON
  matching the CLI contract; verifies argv construction and parsing.
- `export.py` — round-trip an export through a temp directory; verify
  layout and that `bundle.json` re-opens.
- Textual app: rendering snapshots for each of the screens above,
  driven by an integration fixture that pre-builds a real `vtindex`
  archive from `docs/examples/` so the subprocess client tests hit a
  real `vtindex` CLI in isolation.

## Required additions to `vtindex` and `vtextract`

These are the smallest set of upstream changes needed so `vtbrowse` can
stay on the CLI-contract side of the architectural boundary without
ugly workarounds (parsing TTY output, reading the SQLite file, etc.).
Each lands as its own change with tests; `vtbrowse` work blocks on
them.

| # | Tool | Addition | Why `vtbrowse` needs it |
|---|---|---|---|
| F1 | `vtindex` | `vtindex pages <root_id> --json` listing every page of a volume (`ordinal`, `page_key`, `label`, `image`, `metadata`, `transcription` paths) | Powers the page-list screen (2). Without it, `vtbrowse` would have to either walk `vtindex page` once per ordinal or read `volume.json` directly (which loses the on-disk file-existence checks). |
| F2 | `vtindex` | `vtindex item <id> --json` returning the item's title/reference/repository/dates plus its `PageLink`s with `role` (primary/context) | Powers the Item info dialog (9c) and the "context vs primary" annotation. Without it, `vtbrowse` would have to read `items/<id>/identity.json` directly *and* duplicate the schema-normalisation logic in `vtextract.schema`. |
| F3 | `vtindex` | `--json` flag on `vtindex search` results includes `role` per matched page | Same need as F2 from the search-results side. Cheapest fix: extend `SearchResult.matched_pages` to `list[{root_id, page_key, role}]`. |
| F4 | `vtindex` | `vtindex build --json-progress` emitting one JSON object per status update on stdout (replacing the human-readable `BuildReporter` output) | Powers the Build progress modal (13) and the chained Extract→Build modal (15b). Without it, `vtbrowse` parses `BuildReporter`'s text — fragile, and breaks any time a counter label changes. |
| F5 | `vtextract` | `vtextract search --json-progress` (same structured stdout events) | Powers Step 1 of the Extract progress modal (15b). Same rationale as F4. |
| F6 | `vtextract` | `vtextract get --json-progress` (same) | Powers the Export image-backfill progress dialog. Same rationale. |
| F7 | `vtindex` | `vtindex stats --json` already returns `stale: bool`. **No change**, just confirming the contract `vtbrowse` depends on. | Initial staleness check (screen 12) and in-session re-check that drives the stale chip (screen 14). |

F1–F3 are pure additions (new subcommand + extended JSON shape).
F4–F6 are *additive* — the default text output stays the way it is for
existing users; `--json-progress` opts into JSONL-on-stdout.

### JSON progress event shape (F4–F6)

A single shape works for all three tools; each emits one JSON object
per line on stdout, terminated by `\n`. The TUI reads stdout in an
async loop and updates the modal as events arrive.

```json
{"event": "start",    "tool": "vtindex build", "argv": [...]}
{"event": "progress", "phase": "scanning items",   "current": 1842, "total": 2901, "counters": {...}}
{"event": "log",      "level": "info",            "message": "scanning items/0007/18425"}
{"event": "done",     "elapsed_seconds": 14.2,    "counters": {"added": 412, "updated": 87, "unchanged": 1343, "skipped": 3}}
{"event": "error",    "message": "...", "exit_code": 2}
```

`counters` is tool-specific (the keys the existing `BuildReporter`
already exposes for `vtindex build`; the equivalents for
`vtextract search` / `vtextract get`). The modal's bottom log line
binds to the most recent `log` event; the counter block above binds
to the latest `progress.counters`.

## Code shared across `vtindex` / `vtextract` / `vtbrowse`

Pulling these out of where they currently live (mostly inside
`vtextract.index.cli`) before adding a third consumer keeps each one
single-source-of-truth.

| Module (new) | What moves in | Current home | Consumers |
|---|---|---|---|
| `vtextract.theme` | `Theme` dataclass, `THEMES` dict, `_highlight_title`, `_WORD_RE`, `_add_theme_args` | `vtextract.index.cli` | `vtindex` CLI, `vtbrowse` (Rich rendering inside Textual widgets — same colour scheme as `vtindex search`) |
| `vtextract.progress` | (already shared) `BuildReporter` — extend with a `JsonProgressReporter` sibling that emits the F4–F6 event shape | `vtextract.progress` | `vtindex build`, `vtextract search`, `vtextract get`, `vtbrowse` (parser only) |
| `vtextract.search_spec` | `FIELD_MAP` / `OPERANDS` / argv-building helper for a single-clause search | inline in `vtextract.cli` | `vtextract` CLI (extracted), `vtbrowse` (Extract dialog's `Will run:` preview and the actual argv it execs) |

Each move is a non-breaking refactor: `vtextract.index.cli` /
`vtextract.cli` keep their public names by re-exporting from the new
modules.

## Open / deferred questions

- Whether selecting a whole volume (some shortcut on a volume row in the
  page list?) should be a thing. For now, no — the user selects items
  from search results or individual pages from the page list.
- Whether the in-session stale-index chip should ever escalate to a
  blocking dialog (e.g. if the user tries to search while stale).
  Deferred — chip only for now.
- A "recent bundles" picker on `⌃O`. Deferred; just the file dialog for v1.
