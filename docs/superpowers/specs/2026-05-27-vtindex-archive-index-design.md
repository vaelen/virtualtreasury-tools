# vtindex — searchable index over the local archive

**Status:** Design approved (2026-05-27)
**Author:** Andrew C. Young <andrew@vaelen.org>
**Related:** `2026-05-26-virtualtreasury-extractor-design.md` (the extractor that
produces the archive this tool indexes).

## Problem

`vtextract` downloads resources into an on-disk archive (metadata, images,
transcriptions). To find anything in that archive today you must read every
`metadata.json` and every page `.txt` file on each query. We want a second CLI,
`vtindex`, that builds a persistent index so structured searches run without
re-reading the whole archive each time.

Searches combine a **keyword** (in title, description, and/or transcription), a
**time frame**, and optionally a **volume**. The CLI must be automation-friendly
(no interactive UI; clear options, JSON output, and meaningful exit codes) and
must not require a separate database server to be installed.

### Explicitly out of scope

- **Location search.** Investigation of the live archive (51 items) showed the
  only structured geography is the *repository's* county/country (where a
  document is physically held — overwhelmingly "Dublin"), not the place a record
  is *about*. Content place names live only as free text inside titles and
  descriptions, and the knowledge-graph place fields (`kg_label`) are populated
  on a small minority of items. A dedicated location filter would therefore be
  misleading, so we omit it. Place names remain findable via ordinary keyword
  search over title/description.
- Advanced query language, relevance tuning beyond BM25, faceting beyond volume,
  indexing of images, and tracking of all metadata fields. The index records
  only what the three supported query dimensions need.

## Domain facts that shape the design

These were confirmed against the real archive at `~/.vt/archive` and the
fixtures in `docs/examples/`:

- **Dates are well structured and near-universal.** Each item's search hit
  carries `contentDate {gte,lte}` / `contentYears[]` and `createdDate {gte,lte}`
  / `createdYears[]` (present on ~all items). The detail adds `isadgDates` with
  "Created" / "Content Date" timespans. We index both content and created dates.
- **Description is several free-text fields.** We compose an item's description
  from `scopeAndContent`, `archivalHistory`, `archivistsNote`,
  `administrativeOrBiographicalHistory`, and `note` (all lists on the search
  hit), joined with newlines.
- **Transcription is page-level, and a physical page is shared by multiple
  resources** (many-to-many). A resource (`isadgID`) references pages by
  `root_id` + `page_key` in its `metadata.json` `pages[]`. The transcription
  text for a page is the sibling `pages/{root_id}/{page_key}.txt` file
  (`page_key` already ends in `.jpg`, so the file ends in `.jpg.txt`).
- **A resource may reference pages in more than one volume** (`root_id`), via its
  primary and context page refs. Volume → item is therefore many-to-many.
- **An item's transcription pages may not be on disk.** Page `.txt` files exist
  only for volumes that were downloaded; an item must still be indexed from its
  metadata when its transcription pages are absent.
- **Volumes carry a friendly label.** `pages/{root_id}/volume.json` holds
  `{label, reference_code}`, useful for discovery.

## Decisions

1. **Result unit: item-level, page-aware.** A search result is always an item
   (`isadgID`). Pages and transcription text are indexed **once** (mirroring the
   archive's dedup design); a transcription keyword hit resolves to items by
   joining the matched page back through the item↔page relation, and the result
   reports which page(s) matched. We do not duplicate transcription text per
   item.
2. **Index library: SQLite + FTS5.** `sqlite3` ships with the Python stdlib — no
   install, no server, a single index file. FTS5 provides BM25 keyword search
   *and* lets structured filters (date ranges, volume) run in the same query
   engine. The only risk is a Python interpreter compiled without FTS5; we
   detect that and fail with a clear message (see Error handling).
3. **Index location:** a subfolder of the archive,
   `<archive>/index/vtindex.sqlite3`. Keeps the archive root clean; `archive/`
   is already gitignored.
4. **Refresh model: manual, incremental, decoupled.** The index is refreshed by
   re-running `vtindex build`, which is incremental (see below). `vtindex`
   stays fully independent of `vtextract` — no coupling, the index is optional.
5. **Change detection: stat-based fingerprints.** Build compares each source
   file's `(mtime, size)` against a stored fingerprint table. It does not read
   the extractor's `_state.json` (avoids coupling to the extractor's state
   format and catches out-of-band edits).
6. **Progress: the shared `Reporter`.** Build shows a live progress bar through
   the same `rich`-based abstraction the extractor uses (`progress.py`). That
   module is generalized so a neutral single-bar reporter is reusable by build,
   with the extractor's fetch-specific two-bar behavior layered on top (see
   Progress reporting).

## Architecture

A new subpackage `src/vtextract/index/`, following the existing module
discipline (a single DB choke point, pure readers, an orchestrator, a CLI):

| Module | Responsibility | Analogous to |
|---|---|---|
| `index/db.py` | The **only** module issuing SQL. Owns the connection, schema DDL, schema-version check, and FTS5-availability detection. | `client.py` |
| `index/reader.py` | **Pure, no DB.** Reads archive files → plain row dicts (item, volume, page, transcription text). Knows the archive layout and field composition. | `schema.py` |
| `index/builder.py` | Orchestrates a build: walks the archive, diffs against stored fingerprints, upserts/deletes via `db`. | `fetcher.py` |
| `index/query.py` | Translates a `SearchQuery` into SQL; returns `SearchResult`s. | — |
| `index/cli.py` | argparse wiring for the subcommands; resolves the archive path; renders human/JSON output; sets exit codes. | `cli.py` |
| `index/models.py` | Small dataclasses: `SearchQuery`, `SearchResult`, `VolumeInfo`. | `models.py` |

The build reuses the existing `vtextract.progress` module for its progress bar
(no new progress code in the subpackage). A `vtindex` console-script entry point
in `pyproject.toml` → `vtextract.index.cli:main`.

## Progress reporting

Build displays a live progress bar via the same `rich`-based `Reporter`
abstraction the extractor uses, so both CLIs share one progress dependency and
one module (`src/vtextract/progress.py`).

`progress.py` is generalized so its generic, single-bar behavior is reusable
without the fetch-specific vocabulary:

- A reusable reporter exposes neutral operations — size the bar to a total
  (e.g. "Indexing 1240 files"), advance per processed source file, emit status
  lines, and a `finish` summary — with `console`/`enabled` injectable for
  testing and the bar auto-disabled off a TTY (so piped output stays clean),
  exactly as today.
- The extractor's existing two-bar fetch behavior (resources × pages, with
  "fetching/archived/skipping" wording) is preserved by layering it on top of
  the generic reporter; `fetcher.py`/`cli.py` behavior is unchanged.
- `builder.py` drives the generic reporter: set the total to the number of
  candidate source files, advance once per file, and print a `finish` summary
  line mirroring `added/updated/removed/unchanged` (and skipped-malformed).

This is a small, contained refactor of `progress.py`; no behavior change to the
extractor's output.

## Index schema (SQLite + FTS5)

Regular tables:

- `meta(key, value)` — holds `schema_version` and build bookkeeping (last build
  time, counts).
- `item(isadg_id PK, reference_code, title, description, repository,
  content_begin TEXT, content_end TEXT, created_begin TEXT, created_end TEXT,
  content_year_min INT, content_year_max INT, created_year_min INT,
  created_year_max INT, path TEXT)` — dates stored both as ISO bounds and as
  integer year ranges so a bare-year query filters with cheap integer math.
- `volume(root_id PK, label, reference_code)`.
- `page(root_id, page_key, has_text INT, PRIMARY KEY(root_id, page_key))`.
- `item_volume(isadg_id, root_id)` — many-to-many.
- `item_page(isadg_id, root_id, page_key, role)` — many-to-many; `role` is
  `primary`/`context`.
- `source_file(path PK, kind, mtime, size)` — the fingerprint table driving
  incremental builds. `kind` ∈ {`item`, `transcription`, `volume`}.

FTS5 virtual tables:

- `item_fts(title, description)` — one row per item (rowid = item rowid). `--in`
  maps to FTS5 column filters (`{title}:` / `{description}:`).
- `transcription_fts(text)` — one row per page; an auxiliary
  `transcription_fts_map(rowid → root_id, page_key)` ties a hit back to its page,
  then `item_page` ties the page to items.

## Build (incremental)

`vtindex build [--archive PATH] [--rebuild]`:

1. Open/create the index; verify `schema_version`. On mismatch (or `--rebuild`),
   drop and recreate all tables (full rebuild).
2. Walk `items/*/metadata.json`, `pages/*/volume.json`, and
   `pages/*/*.jpg.txt`. For each, compare `(mtime, size)` to `source_file`:
   - **new** → parse via `reader`, insert rows, insert fingerprint.
   - **changed** → re-parse, upsert rows (delete + reinsert dependent join/FTS
     rows for that source), update fingerprint.
   - **unchanged** → skip (no open/parse).
3. **Vanished** sources (in `source_file`, absent on disk) → delete their rows
   (item and its joins/FTS, or page and its joins/FTS), delete fingerprint.
4. Update `meta` counts/timestamp. Print a one-line summary
   (`added/updated/removed/unchanged`).

A live progress bar (the shared `Reporter`) tracks the candidate source files as
they are processed; it is disabled automatically off a TTY. The final summary
line is emitted through the same reporter.

Cost scales with what changed, not archive size — stat is cheap and only changed
files are opened. This is the normal post-download refresh path.

## Search

`vtindex search [--archive PATH] QUERY [options]`:

| Option | Meaning | Default |
|---|---|---|
| positional `QUERY` | FTS5 keyword expression | (optional; omit for filter-only search) |
| `--in title,description,transcription` | which text fields to search | all three |
| `--from YEAR\|DATE` / `--to YEAR\|DATE` | time-frame bounds; bare year or ISO date | unbounded |
| `--date-type content\|created` | which date the time frame applies to | `content` |
| `--volume ROOTID` | restrict to items referencing this volume | none |
| `--limit N` | max results | 50 |
| `--json` | structured output | off (human table) |

Semantics:

- **Keyword** searches `item_fts` (title/description per `--in`) for items, and
  `transcription_fts` (if transcription in `--in`) for pages → items; the item
  id sets union. Score = best (lowest) BM25 across the sources that matched.
- **Time frame** is an overlap test against the selected date type: an item
  matches when its range intersects `[from, to]`. Year inputs use the integer
  year columns; ISO-date inputs use the ISO bound columns.
- **Volume** filters via `item_volume`.
- All supplied filters AND together. With no `QUERY`, results are filtered-only
  (e.g. "everything in volume X between 1700 and 1750"), ordered by date.

Output (per result, JSON): `isadg_id`, `title`, `reference_code`, `repository`,
`content_date`, `created_date`, `matched_fields` (subset of
title/description/transcription), `matched_pages` (`{root_id, page_key}` list,
empty unless a transcription hit), `score`, and `path` (on-disk item dir). The
human table shows id, date, title, reference code, and matched fields.

## Discovery / status subcommands

- `vtindex volumes [--archive PATH] [--json]` — list volumes
  (`root_id`, `label`, `reference_code`, indexed item count) so an agent can
  discover valid `--volume` values.
- `vtindex stats [--archive PATH] [--json]` — index summary (item/volume/page
  counts, schema version, last build time) and a **staleness** indication
  (whether the archive has changed since the last build).

## CLI conventions

- **Archive path resolution:** `--archive`, else `$VT_ARCHIVE`, else `./archive`.
- **Exit codes (grep convention):**
  - `0` — completed with ≥1 result (or, for non-search commands, success).
  - `1` — completed with **no matching results**.
  - `2` — error or usage problem: bad/missing archive, **index not built**
    (message directs the user to run `vtindex build`), schema incompatibility
    requiring `--rebuild`, FTS5 unavailable, or argparse usage error.
- **Staleness is a warning, not an error.** If the index exists but the archive
  changed since the last build, `search` still serves results and prints a
  warning to **stderr** suggesting `vtindex build`.

## Error handling

- **FTS5 unavailable** in the running interpreter: detected in `db.py` at
  build/open time via a probe (`CREATE VIRTUAL TABLE ... USING fts5`); raise a
  clear error and exit `2` with guidance.
- **Missing index** on `search`/`volumes`/`stats`: exit `2`, instruct to build.
- **Corrupt / partially written index:** schema-version / integrity check on
  open; advise `--rebuild`.
- **Malformed `metadata.json`** for an item during build: skip that item, record
  it in the build summary (count of skipped), continue (one bad file must not
  abort the whole build). Absent transcription `.txt` files are normal and
  simply mean `has_text = 0`.

## Testing (TDD, no network)

A small committed fixture archive under `tests/` (a few items spanning ≥2
volumes, with and without transcription `.txt`, including one many-to-many
shared page and one item referencing two volumes). Tests cover:

- `reader`: field extraction and description composition; date parsing
  (year + ISO); volume label parsing; absent-transcription handling.
- `builder`: full build row counts; **incremental** add / change / vanish /
  unchanged-skip; `--rebuild`; malformed-metadata skip.
- `query`: keyword (each `--in` combination), transcription hit → correct item
  set and `matched_pages`, date overlap (year and ISO, content vs created),
  volume filter, filter-only search, AND-combination, `--limit`.
- `cli`: exit codes (0 / 1 / 2), JSON shape, `volumes` / `stats`, staleness
  warning, missing-index and (simulated) FTS5-unavailable paths.
- `progress`: the generalized reporter advances/finishes correctly with
  `enabled=False` (no TTY); existing extractor `Reporter` tests still pass
  unchanged.

No network and no real credential are involved at any point.

## Module/packaging summary

- New: `src/vtextract/index/{__init__,db,reader,builder,query,cli,models}.py`.
- Modified: `src/vtextract/progress.py` — generalized so its single-bar reporter
  is reusable by build; extractor's two-bar fetch behavior preserved on top.
- `pyproject.toml`: add `vtindex = "vtextract.index.cli:main"` to console
  scripts. (`rich` is already a dependency.)
- Docs: README usage section for `vtindex`; this spec linked from CLAUDE.md.
