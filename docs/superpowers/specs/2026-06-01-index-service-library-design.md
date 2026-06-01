# Index service library — in-process index access for vtbrowse

**Status:** Design approved (2026-06-01)
**Author:** Andrew C. Young <andrew@vaelen.org>
**Related:**
- `2026-05-27-vtindex-archive-index-design.md` (the index this work refactors access to).
- `2026-05-29-vtbrowse-tui-design.md` (the TUI whose subprocess constraint this work replaces; its
  "Architectural boundaries" section is amended here).

## Problem

`vtbrowse` (the Textual TUI) is currently forbidden from importing the index internals
(`vtextract.index.{db,query,builder}`). To read the index it shells out: `IndexClient` spawns a
`vtindex <command> --json` subprocess per call and parses the JSON. Every read — every search, page
navigation, volume listing, item lookup, startup `stats` — is therefore a fresh OS process:
interpreter startup, module imports, `sqlite3.connect`, and `_ensure_schema`, before any query runs.

The index database has grown large enough that re-opening it on every call causes a noticeable delay
and repeated memory cost. The subprocess-per-call model is the bottleneck.

We want to **drop the "vtbrowse must subprocess vtindex" constraint** and replace it with a softer,
more useful one: *all access to the archive's index goes through a shared library layer; no consumer
touches the backend store directly.* The library is shared by both the `vtindex` CLI and `vtbrowse`,
which removes the duplicated enrichment logic and preserves a single abstraction boundary so the
index's backend store (today SQLite + FTS5) can be swapped later without touching consumers.

The performance win comes from `vtbrowse` opening the index **once** and reusing a long-lived
connection in-process, instead of paying full process + DB-open cost per call.

### Goals

- A shared, synchronous **index service** library that is the single public entry point to the
  index, owning one long-lived read connection.
- Both `vtindex` CLI and `vtbrowse` consume only this library — never `db`/`query`/`builder`.
- `vtbrowse` reads the index in-process (DB opened once), and runs index **builds** in-process too
  (worker thread + in-process progress reporter + cooperative cancellation).
- The public API returns typed result objects (dataclasses), not loose dicts.
- `vtindex` CLI output (human tables and `--json`) stays byte-for-byte unchanged.

### Explicitly out of scope

- **`ExtractClient`.** It wraps the *network* tool `vtextract` (HTTP fetches against the live site)
  and remains a subprocess. Only the `vtindex build` half of the extract→build chain moves
  in-process.
- **Changing what the index stores or how search ranks.** Schema, FTS, BM25, the `SearchQuery`
  semantics, date handling, and staleness detection are unchanged. This is an *access-layer*
  refactor, not an index redesign.
- **Replacing the SQLite backend.** This work makes a future swap *possible* by enforcing the
  boundary; it does not perform one.
- **`vtindex` CLI surface.** Subcommands, flags, exit codes, and output formats are preserved.

## Current architecture (what we are changing)

- `index/db.py` — `IndexDB`, the single SQL choke point. Owns the connection, schema, upserts, and
  the low-level search/read primitives (`item_fts_search`, `filter_items`, `get_page`,
  `page_at_ordinal`, `pages`, `item`, `volumes`, `volume`, `counts`, …).
- `index/query.py` — pure `search(db, SearchQuery) -> list[SearchResult]` composition over `db`
  primitives.
- `index/builder.py` — incremental, fingerprint-based `build(archive, *, rebuild, reporter)`; opens
  its **own** short-lived `IndexDB`, commits, closes. Also `is_stale(db, archive)` and
  `INDEX_RELPATH`.
- `index/models.py` — `ItemRow`, `VolumePage`, `VolumeRow`, `SearchQuery`, `SearchResult`,
  `VolumeInfo`, `BuildStats`, `PageLink`.
- `index/reader.py` — pure archive-file parsing (`read_item`, `read_volume`, `read_transcription`).
- `index/cli.py` — argparse **and** all result enrichment + presentation. The enrichment functions
  (`_page_dict` resolves on-disk `image`/`metadata`/`transcription` paths, `_result_dict`,
  `_page_nav_dict`, the previous/current/next nav assembly, the `item` assembly, stale warnings) are
  what actually define the JSON contract the TUI depends on — **not** the raw `db` rows.
- `tui/index_client.py` — `IndexClient`, the subprocess choke point. Async methods (`search`, `page`,
  `pages`, `volumes`, `item`, `stats`, `build_stream`) each spawn `vtindex … --json` and parse the
  result. `build_stream` drains JSONL progress and SIGTERM/SIGKILLs the child on cancel.
- `tui/` consumers of `IndexClient`: `app.py` (`stats`, `search`, `build_stream`), `screens/volumes.py`
  (`volumes`), `screens/pages.py` (`pages`), `screens/transcription.py` (`page`), `dialogs/info.py`
  (`item`, `volumes`, `pages`).
- `tests/test_no_direct_db.py` — enforces that nothing in `tui/` imports
  `vtextract.index.{db,query,builder}` or `vtextract.{fetcher,client}`.

The critical observation: the TUI's real contract is the **enriched** shapes produced by `cli.py`,
which are richer than `db`'s return values (they add resolved file paths and nav structure). Any
in-process replacement must hand the TUI the *same enriched data*. That enrichment is therefore the
thing that must move into the shared library.

## Target architecture

### 1. `index/service.py` — `IndexService` (new)

A synchronous facade and the single public entry point to the index. It owns one long-lived
`IndexDB` read connection and the archive root path (needed for file-path enrichment). All the
enrichment logic currently in `cli.py` moves here. `db.py` remains the SQL choke point;
`query.py`/`builder.py` remain internal collaborators of the service.

```python
class IndexService:
    def __init__(self, archive: Path): ...        # opens IndexDB(archive/INDEX_RELPATH) once
    # reads (return typed DTOs):
    def search(self, q: SearchQuery) -> list[SearchHit]: ...
    def page(self, root_id: str, page_key: str) -> PageNav | None: ...
    def pages(self, root_id: str) -> list[PageRef]: ...
    def volumes(self) -> list[VolumeInfo]: ...
    def item(self, isadg_id: int) -> ItemDetail | None: ...
    def stats(self) -> IndexStats: ...
    def is_stale(self) -> bool: ...
    # build (write path):
    def build(self, *, rebuild: bool = False, reporter=None,
              cancel: "threading.Event | None" = None) -> BuildStats: ...
    # lifecycle:
    def reopen(self) -> None: ...                 # close + re-open the read connection
    def close(self) -> None: ...
```

- **Enrichment lives here.** `search` calls `query.search(db, q)` then enriches each `SearchResult`
  into a `SearchHit` (resolving `matched_pages` to `PageRef`s). `page` assembles the
  previous/current/next `PageNav` from `db.get_page`/`db.page_at_ordinal`/`db.volume`. `pages`,
  `item`, `stats` likewise wrap `db` rows into DTOs.
- **Path resolution** (`image`/`metadata`/`transcription` absolute paths, existence-checked) becomes
  a pure helper `page_files(archive, root_id, page_key) -> PageFiles` in `reader.py` (its home for
  archive-file knowledge), composed by the service. This removes `_page_file`/`_page_dict` from
  `cli.py`.
- **`build`** delegates to `builder.build(...)` (which opens its own connection), passing through the
  reporter and a new cooperative `cancel` event. It does **not** reuse the read connection. After a
  build the *caller* is expected to `reopen()` the read connection (the service does not auto-reopen,
  keeping `build` connection-agnostic; the TUI adapter calls `reopen()` on completion).
- **Open failures** (`FileNotFoundError` for a missing index, `SchemaMismatch`, `Fts5Unavailable`)
  propagate as exceptions for the caller to handle — exactly the conditions `cli.py.main()` and the
  TUI startup already branch on.

### 2. `index/models.py` — public DTOs (extended)

Typed result objects form the public contract. New/extended dataclasses:

- `PageFiles` — `image: str | None`, `metadata: str | None`, `transcription: str | None` (resolved
  absolute paths or `None` when absent on disk).
- `PageRef` — `root_id`, `page_key`, `ordinal: int | None`, `label: str | None`, plus the
  `PageFiles` fields (flattened, to match today's JSON), and optional `role: str | None` for
  matched/item contexts.
- `PageNav` — `volume: VolumeHeader` (root_id, title) + `previous/current/next: PageRef | None`.
- `SearchHit` — the enriched `SearchResult`: scalar fields as today plus `matched_pages: list[PageRef]`
  (each carrying `role`) and `path`.
- `ItemDetail` — item header fields + `pages: list[PageRef]` (with `role`).
- `IndexStats` — `items`, `volumes`, `pages`, `schema_version`, `stale`.
- `VolumeSummary` — the existing `VolumeInfo` (root_id, label, reference_code, item_count, title) is
  reused as-is; the `volumes()` return type is `list[VolumeInfo]`. No new type, no new fields.

`SearchResult` (raw, from `query.py`) stays internal; the service maps it to `SearchHit`. Each DTO
carries a `to_dict()` (or a sibling serializer) producing the **exact** current JSON field set and
order — see §3.

### 3. `index/cli.py` — thin presentation over the service

Each `_cmd_*` constructs an `IndexService`, calls one method, and renders: a Rich table (human) or
`json.dumps(dto.to_dict())` (`--json`). The enrichment/path helpers are deleted from `cli.py` (moved
to the service/reader). `main()` keeps its existing exception→exit-code mapping.

**Hard requirement:** `--json` output and the human tables remain byte-for-byte identical. The DTO
serializers are pinned to the current shapes; the existing CLI JSON and snapshot tests are the
guard. `build` keeps using `BuildReporter`/`JsonBuildReporter` via the service's `build`.

### 4. `tui/index_client.py` — in-process gateway (rewritten, same name)

The class stays named `IndexClient` (it is still a client *of* the index; keeping the name minimizes
import churn across `app.py`/screens/dialogs). Its docstring and contract change from "subprocess
choke point" to "in-process gateway: the only place in `tui/` that holds an `IndexService`."

> Naming alternative (decide at review): rename to `IndexGateway` to signal it is no longer a
> subprocess wrapper. Chosen default is to keep `IndexClient` for lower churn.

Concurrency model — **single dedicated executor thread**:

- The gateway creates `ThreadPoolExecutor(max_workers=1)` and constructs/owns the `IndexService` on
  that thread. Every read method (`search`, `page`, `pages`, `volumes`, `item`, `stats`) dispatches
  the corresponding sync service call to that one executor via `loop.run_in_executor`. This keeps the
  Textual event loop responsive *and* confines the SQLite connection to exactly one thread (no
  `check_same_thread` hazard; calls are naturally serialized).
- Read methods now return **DTOs**. TUI consumers switch from `row["page_key"]` to `row.page_key`.
  This is the main TUI churn (see §5).
- `close()` shuts the executor down (closing the service on its thread). Called on app exit.

Considered and rejected: `asyncio.to_thread` + a `threading.Lock`. It works but spreads the
connection across pool threads and needs `check_same_thread=False` plus explicit locking; the single
dedicated thread is simpler and strictly serial.

### 5. In-process build + cancellation

`build_stream(...)` stays an **async generator yielding the same `ProgressEvent`s**, so `ProgressModal`
and the extract→build chain in `app.py` are untouched at the call site. Internally:

- It runs `service.build(rebuild=…, reporter=<queue reporter>, cancel=<threading.Event>)` on a worker
  thread (a second executor / `loop.run_in_executor`, distinct from the read thread because a build
  can run for a while and must not block reads).
- A new **in-process progress reporter** implements the same call surface as `JsonBuildReporter`
  (`start`, `advance`, `finish`, `emit_error`) but pushes typed `ProgressEvent`s onto an
  `asyncio.Queue` (thread-safe hand-off via `loop.call_soon_threadsafe`). The generator drains the
  queue and yields events until a terminal `done`/`error`.
- **Cancellation:** `builder.build()` gains a cooperative `cancel: threading.Event | None` parameter,
  checked once per file in its main loop; when set it stops, commits/cleans up, and returns. When the
  generator's consumer `aclose()`s (e.g. the user cancels the modal), the gateway sets the event —
  replacing the old SIGTERM/SIGKILL dance. The reporter still emits a terminal event.
- **Read freshness:** on build completion the gateway calls `service.reopen()` so subsequent reads
  see the new data. `reopen()` is mandatory after `--rebuild`, which drops and recreates tables/FTS,
  leaving any held connection with a stale schema view.

The chained extract→build flow in `app.py._after_extract_form` is preserved: step 1 stays the
`ExtractClient` subprocess (network fetch); step 2 becomes the in-process `index.build_stream(...)`.

### 6. Boundary test + docs, retargeted

`tests/test_no_direct_db.py` keeps forbidding `tui/` from importing
`vtextract.index.{db,query,builder}` and `vtextract.{fetcher,client}`. `index.service` and
`index.models` are the **allowed** seam (no test change needed — they were never in `FORBIDDEN`; the
test now passes *because* the gateway imports only `service`/`models`). The test's module docstring
and the assertion message are updated to describe the new rule ("go through `index.service`").

`CLAUDE.md` is updated: the `tui/` "Architectural boundary" bullet changes from "shells out:
`IndexClient` wraps `vtindex` subprocess calls" to "in-process: `IndexClient` is the sole holder of an
`IndexService`; `tui/` never imports `index.{db,query,builder}`." The `index/` bullet notes
`service.py` as the public entry point and `cli.py` as thin presentation over it.

## Data flow (after)

Read (e.g. a search), `vtbrowse`:
```
pane → IndexClient.search(...)            (async)
     → run_in_executor(read_thread)
        → IndexService.search(SearchQuery)        (sync, persistent connection)
           → query.search(db, q) → enrich → list[SearchHit]
     ← list[SearchHit] (DTOs)
```

Read, `vtindex` CLI:
```
cli._cmd_search → IndexService.search(...) → list[SearchHit]
                → json.dumps([h.to_dict() …])  |  Rich table
```

Build, `vtbrowse`:
```
ProgressModal → IndexClient.build_stream()        (async generator)
   run_in_executor(build_thread):
       IndexService.build(reporter=QueueReporter, cancel=Event)
          → builder.build(...)  (own connection; checks cancel per file)
   QueueReporter → asyncio.Queue → yield ProgressEvent …
   on completion → IndexService.reopen()  (refresh read connection)
```

## Error handling

- **Missing index / schema mismatch / no FTS5:** `IndexService.__init__` (or first use) raises
  `FileNotFoundError` / `SchemaMismatch` / `Fts5Unavailable`. The CLI maps these to exit 2 (as today);
  the TUI startup catches them and prompts to build (as today, where a missing index already triggers
  the build flow).
- **Build errors:** surface as a terminal `error` `ProgressEvent` (TUI) and a non-zero build outcome
  / stderr (CLI), matching current behavior.
- **Cancellation:** cooperative; a cancelled build yields no synthetic error event (it ends cleanly),
  mirroring today's "don't emit error on cancel" rule.
- **Stale index:** `is_stale()` is surfaced by the service; the CLI prints the same stderr warning;
  the TUI may surface it where it does today.

## Testing strategy

TDD throughout; tests run against fixtures, never the network.

- **`IndexService` unit tests** (new): build a tiny index from fixtures, then assert each method
  returns the right DTOs, including path enrichment (present/absent files), page nav
  (first/middle/last/missing-ordinal), item assembly, stats, and `is_stale`. `reopen()` reflects a
  rebuild.
- **CLI parity tests** (existing + augmented): the current `vtindex … --json` and table snapshot
  tests must stay green unchanged — they are the guarantee that moving enrichment into the service
  did not alter output. Add explicit byte-equality assertions for the JSON shapes if not already
  pinned.
- **In-process build + cancel tests** (new): drive `IndexClient.build_stream` against a fixture
  archive; assert the `ProgressEvent` sequence matches the subprocess version's, and that setting the
  cancel path stops the build and ends without a synthetic error event. Assert `reopen()` is invoked
  and post-build reads see new rows.
- **TUI consumer tests / snapshots** (updated): adjust for attribute access on DTOs; existing TUI
  snapshot baselines should be unaffected (rendered output is unchanged) — regenerate only if a
  screen genuinely changes.
- **Boundary test:** `tests/test_no_direct_db.py` continues to pass; its message/docstring updated.

## Risks / trade-offs

- **TUI churn from dict→DTO.** Touches `app.py` and four screen/dialog modules. Mitigated by keeping
  field names identical to today's dict keys, so the change is mechanical (`x["k"]` → `x.k`).
- **SQLite across threads.** Mitigated by confining the read connection to one dedicated executor
  thread and giving builds their own connection.
- **CLI output drift.** The single biggest correctness risk. Mitigated by pinned serializers and the
  existing JSON/snapshot tests as a hard gate.
- **Long build blocking reads.** Avoided by running builds on a separate thread from reads; the read
  connection stays usable during a build (SQLite readers see the last committed state).

## Success criteria

- `vtbrowse` opens the index once and performs all reads in-process; no `vtindex` subprocess is
  spawned for reads or builds.
- `vtindex` CLI behavior (tables, `--json`, exit codes) is unchanged; all existing tests pass.
- `tui/` imports only `index.service` + `index.models` from the index package; the boundary test
  enforces it.
- The enrichment logic exists in exactly one place (the service), shared by CLI and TUI.
