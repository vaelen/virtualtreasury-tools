# CLAUDE.md

Guidance for working in this repository.

## What this is

`vtextract` — a Python CLI that runs searches against
[virtualtreasury.ie](https://virtualtreasury.ie) (the Virtual Record Treasury
of Ireland / "Beyond 2022" project) and downloads each matching resource's
metadata and transcriptions — and, with `--images`, full-resolution page
images — into a resumable local archive. The public site is an Angular SPA
over a DSpace backend with IIIF image delivery; this tool replicates the
requests the browser makes.

## Where things are documented

- **Design spec** (the why + the reverse-engineered API):
  `docs/superpowers/specs/2026-05-26-virtualtreasury-extractor-design.md`
- **Implementation plan** (task-by-task):
  `docs/superpowers/plans/2026-05-26-virtualtreasury-extractor.md`
- **Captured API samples / test fixtures**: `docs/examples/`
  (`doc-search/` and `item/<call>/`). Treat these as read-only fixtures.
- **Follow-up work**: `TODO.md`
- **User-facing usage**: `README.md`

## Running things

This project uses [uv](https://docs.astral.sh/uv/). `uv sync --extra dev`
provisions the `.venv` from the committed `uv.lock`; `uv run` auto-syncs before
each invocation, so prefer it over activating the venv manually.

- **Tests:** `uv run pytest` — they run entirely against the committed fixtures
  in `docs/examples/`; they never hit the live site or use a real credential.
  Keep it that way.
- **CLI:** `uv run vtextract search --title --all <keywords> --out ./archive --context-pages 1`
  (subcommands: `search`, `get`, and `auth`; searches are built from flags, not a
  URL; see `docs/search-query.md`). Images are **opt-in** via `--images` on
  `search`, `get`, and `refresh`; the default fetches metadata + manifest +
  per-page transcriptions only. `get <refcodes/ids...>` pulls known resources
  directly (reference codes normalise ` `/`/` → `-`), reusing the same fetch flow.
  A `refresh` command (and `--refresh` on `search`/`get`) re-fetches metadata for
  already-archived resources and backfills missing transcriptions; with
  `--images` it also HEAD-verifies image sizes against disk and re-downloads
  mismatches. The full-archive `refresh` confirms first (`-y` to skip).
- **Index CLI:** `.venv/bin/vtindex build --archive ./archive` then
  `.venv/bin/vtindex search "<keyword>" --archive ./archive [--json]`, or
  `.venv/bin/vtindex page <rootID>/<page_key> --archive ./archive` for
  previous/next page navigation within a volume.
- **TUI:** `uv run vtbrowse [--archive PATH]` — interactive browser over an
  existing archive + index. See `README.md` for key bindings and workflow.
  TUI tests: `uv run pytest tests/tui/ -v`; snapshot baselines live in
  `tests/tui/__snapshots__/`; regenerate with `--snapshot-update` after
  intentional screen changes.
- **Credentials** come only from the config file `~/.vt/vt.toml`
  (`[extract.auth].token`), written by `vtextract auth`. There are no `VT_*`
  env vars. Never hardcode the credential in source or tests; tests pass a
  `--config` path to a `tmp_path` file.

`src/` layout; `pyproject.toml` sets `pythonpath = ["src", "."]` so tests import
`vtextract` (from `src/`) and the `tests.conftest` helpers (from the repo root)
under `uv run pytest`. `archive/`, `.venv/`, and `*.egg-info/` are gitignored;
`uv.lock` is committed.

## Architecture (one responsibility per module, under `src/vtextract/`)

- `config.py` — `load_config(path)` → `Config` (auth header, archive, base URL,
  delay…) from `~/.vt/vt.toml`; plus `set_token`/`make_token` for `auth`.
- `client.py` — the **single HTTP choke point**. Nothing else makes raw HTTP
  calls. Owns auth header, rate-limit delay, retry/backoff; raises on all error
  statuses, retries only `{429,500,502,503,504}`.
- `models.py` — `Page`, `PageRef`, `Record` dataclasses.
- `search.py` — `criteria_to_params` (SearchCriteria → query params),
  `build_body`, `iter_results` (doc_search pagination) for the `search` command.
- `schema.py` — **pure functions, no I/O**: parse manifests → `Page`s, extract
  the volume root id from canvas `@id`s, reconstruct transcription text, select
  context canvases, `normalize_reference_code` (` `/`/` → `-`), and
  `normalize_record(detail)` (Record built solely from the detail object).
- `archive.py` — owns the on-disk store and `_state.json` resume state.
- `fetcher.py` — orchestrates per-resource retrieval using the above. A "hit"
  carries only a lookup key; `_fetch_detail` resolves it to the detail object
  (numeric `isadgID` → by id, else `displayReferenceCode` → by reference-code
  query), and the detail's `id` is the canonical isadgID.
- `cli.py` — argparse wiring; `_make_transport()` is a test seam (returns
  `None` in prod; tests monkeypatch it to inject an `httpx.MockTransport`).
- `index/` (subpackage) — the `vtindex` CLI. `db.py` is the **single SQL choke
  point** (SQLite + FTS5; analogous to `client.py`). `reader.py` is pure
  archive-file parsing (analogous to `schema.py`). `builder.py` does an
  incremental, stat-fingerprint build (analogous to `fetcher.py`). `query.py`
  composes a search from `db` primitives. `cli.py` wires `build`/`search`/
  `volumes`/`stats`. Build progress reuses `progress.BuildReporter`.
- `tui/` (subpackage) — the `vtbrowse` TUI. **Architectural boundary:** `tui/`
  never imports `vtextract.index.{db,query,builder}` or
  `vtextract.{fetcher,client}` directly. Instead it shells out: `IndexClient`
  wraps `vtindex` subprocess calls; `ExtractClient` wraps `vtextract` subprocess
  calls; `ArchiveReader` does direct on-disk file reads. CI enforces this with
  `tests/test_no_direct_db.py`. Module map:
  - `bundle.py` — selection model (the curated page list + load/save/merge).
  - `index_client.py` — subprocess wrapper for `vtindex` (`build`, `search`,
    `page`, `volumes`).
  - `extract_client.py` — subprocess wrapper for `vtextract` (`search` with a
    single clause; triggers index rebuild on completion).
  - `archive_reader.py` — direct file reads (metadata, page JSON, image paths).
  - `progress_events.py` — typed JSONL event parser for progress streams.
  - `export.py` — bundle folder / zip writer.
  - `app.py` + `screens/` + `dialogs/` + `panes/` — the Textual application.
- Three top-level shared modules added in Phase A of the TUI work:
  - `theme.py` — shared colour constants and Rich/Textual theme helpers.
  - `search_spec.py` — `SearchSpec` dataclass (single-clause search parameters
    shared between `vtindex` and `vtbrowse`).
  - `progress.py` — extended with `BuildReporter` and JSONL event emission
    for the TUI progress pane.

## Domain model (important, non-obvious)

- A **resource** (`isadgID`, an int) is a catalogued entity returned by search.
  A **physical page** (a Loris image filename) is the scanned image. The
  relationship is many-to-many: one page can carry several resources; one
  resource can span several pages.
- **Both the image and the transcription are page-level, not resource-level.**
  The transcription annotation list covers the whole physical page (all records
  on it); it cannot be cleanly split per resource.
- Pages are therefore stored **once** in a shared store grouped by volume:
  `archive/pages/{rootID}/`. Resources live in `archive/items/{isadgID}/` and
  **reference** pages (deduped by Loris id + checksum).
- **Images are opt-in (`--images`)**; transcriptions and metadata are always
  fetched. Each resource's `_state.json` entry records `images_downloaded`, so
  resume is mode-aware: a metadata-only resource gets its images backfilled on a
  later `--images` run, and a fully-imaged resource is skipped by a later
  metadata-only run. Legacy entries without the field are treated as fully
  imaged.
- The **IIIF manifest is the source of truth** for which images/transcriptions
  exist — do NOT trust the `hasImages` / `hasTranscriptions` flags (a sample had
  `hasTranscription: false` yet a populated annotation list).
- Per-item retrieval starts from the identity-statement detail, fetched either
  `GET /rest/isadg-identity-statements/{id}` (by id) or
  `GET /rest/isadg-identity-statements/?isadgReferenceCode={code}` (by reference
  code — same detail shape, its `id` is the isadgID). Then keyed by that id:
  `GET /iiif/v1/{id}/manifest` (images + annotation-list URLs), then each
  annotation list. Context pages come from the **volume** manifest
  `GET /iiif/v1/{rootID}/manifest`, where `rootID` is parsed from a canvas `@id`.

## Conventions

- **TDD**: write the failing test, see it fail, implement minimally, see it
  pass, commit. Every feature commit pairs code with its test.
- Tests use `httpx.MockTransport` + the committed fixtures; no network.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`).
- Keep files small and single-purpose; only `client.py` performs HTTP.
- Be a polite client: the rate-limit delay and retries exist for a reason; this
  hits someone else's archive with a shared credential.
