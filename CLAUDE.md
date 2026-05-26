# CLAUDE.md

Guidance for working in this repository.

## What this is

`vtextract` — a Python CLI that runs searches against
[virtualtreasury.ie](https://virtualtreasury.ie) (the Virtual Record Treasury
of Ireland / "Beyond 2022" project) and downloads every matching resource's
full-resolution images, metadata, and transcriptions into a resumable local
archive. The public site is an Angular SPA over a DSpace backend with IIIF
image delivery; this tool replicates the requests the browser makes.

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
  (subcommands: `search` and `auth`; searches are built from flags, not a URL;
  see `docs/search-query.md`)
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
  `build_body`, `iter_results` (pagination).
- `schema.py` — **pure functions, no I/O**: parse manifests → `Page`s, extract
  the volume root id from canvas `@id`s, reconstruct transcription text, select
  context canvases, normalize records.
- `archive.py` — owns the on-disk store and `_state.json` resume state.
- `fetcher.py` — orchestrates per-resource retrieval using the above.
- `cli.py` — argparse wiring; `_make_transport()` is a test seam (returns
  `None` in prod; tests monkeypatch it to inject an `httpx.MockTransport`).

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
- The **IIIF manifest is the source of truth** for which images/transcriptions
  exist — do NOT trust the `hasImages` / `hasTranscriptions` flags (a sample had
  `hasTranscription: false` yet a populated annotation list).
- Per-item retrieval is three calls keyed by `isadgID`:
  `GET /rest/isadg-identity-statements/{id}` (metadata),
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
