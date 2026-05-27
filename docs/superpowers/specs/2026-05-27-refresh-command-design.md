# Refresh command + `--refresh` flag — design

**Date:** 2026-05-27
**Status:** approved, pending implementation

## Problem

Once a resource is archived, re-running `search`/`get` skips it: `_extract`
short-circuits on `archive.is_resource_complete(isadg_id)` before any request,
and page images are skipped via the state-based `has_page` check. There is no
way to (a) regenerate derived item metadata (e.g. the `volume.json` ordering
added recently) for already-archived resources, or (b) detect image files on
disk that are truncated/corrupt/out of date relative to the server.

A `HEAD` probe against the Loris image URL was verified to work: it returns
`200` with a `Content-Length` that matches the on-disk byte size exactly, using
the same `Authorization: Basic <token>` header the client already sends. Note
that the `Last-Modified` header reflects Loris's on-demand render time, not a
stable source timestamp, so **byte size is the only reliable integrity signal**
from a HEAD.

## Goals

- A `refresh` command that walks every archived item, re-fetches its metadata,
  and HEAD-verifies each referenced image against the on-disk size, re-downloading
  mismatched or missing images.
- `--refresh` flags on `search` and `get` that do the same thing but scoped to
  the command's own results / identifiers.
- A confirmation gate on the full `refresh` command (it is costly), bypassable
  with `-y/--yes`.

## Non-goals

- Re-fetching page transcriptions for images that pass the HEAD check (decided:
  item-level metadata only; a page's transcription is re-fetched only when that
  page's image is re-downloaded).
- Using `Last-Modified` for staleness (unreliable, see above).
- Parallelism / concurrency. Refresh stays sequential and rate-limited — it
  hits someone else's archive with a shared credential.
- A standalone "verify without re-fetching metadata" mode. Refresh always
  re-fetches item metadata.

## Decisions (from brainstorming)

1. **On size mismatch or missing image: re-download** (self-healing). Metadata
   is always re-fetched regardless.
2. **"Re-fetch metadata" = item-level only**: item detail, IIIF manifest,
   `volume.json`, and the resource record. Page transcriptions/annotation lists
   are re-fetched only as a side effect of re-downloading their image.
3. **`refresh` runs as a single in-process `_extract` over all items**, not
   literal per-item subprocesses — semantically equivalent to
   `get --refresh <every id>` but with one shared client, rate-limiter, and
   root-manifest cache.
4. **HEAD failure / absent `Content-Length` → "unverified"**: leave the file as
   is, warn, and list it in the summary. Do not re-download blindly, do not fail
   the item.

## Architecture

Thread a single `refresh: bool` through the existing fetch path rather than
duplicating it:

```
cli (search/get/refresh) → _extract(refresh) → fetch_resource(refresh)
                                              → _ensure_page(refresh, verified)
                                                   → client.head(url)  [verify]
                                                   → client.get_bytes  [re-download on mismatch]
```

### Component 1 — `client.head`

`src/vtextract/client.py`:

```python
def head(self, url: str) -> int | None:
    """HEAD a URL; return its Content-Length in bytes, or None if absent."""
    response = self._request("HEAD", url)
    length = response.headers.get("content-length")
    return int(length) if length is not None else None
```

Reuses `_request` (throttle, retry on `RETRY_STATUS`, `raise_for_status`). Keeps
`client.py` the single HTTP choke point. No other module issues HTTP.

### Component 2 — refresh-aware page handling in `fetcher.py`

`_ensure_page` gains `refresh: bool` and a run-scoped `verified: set[str]`
(keyed `"{root_id}/{page_key}"`) so a physical page shared across items is
HEAD-checked at most once per run.

Current skip:
```python
if archive.has_page(page.root_id, page.page_key):
    return
```
becomes, in refresh mode, a verify-or-redownload decision:

- If the page was already verified this run → record the `PageRef`, return.
- Else compute the verification outcome:
  - On-disk file missing → **download** (fall through to the existing block).
  - HEAD `Content-Length` is `None` or `client.head` raised → **unverified**:
    record the `PageRef`, report it, return (leave file as-is).
  - HEAD size == on-disk `stat` size → **ok**: record `PageRef`, return.
  - HEAD size != on-disk size → **mismatch**: download (existing block), which
    re-fetches the annotation list/text and updates `_state.json` size/sha.
- Mark `"{root_id}/{page_key}"` verified.

Non-refresh behavior is unchanged.

`fetch_resource` gains `refresh: bool` (default `False`) and a
`_verified_pages: set | None` run param (alongside the existing
`_root_manifest_cache`). It always re-fetches the detail + manifest and rewrites
the item record and `volume.json` (already its behavior); it forwards `refresh`
and the verified set to `_ensure_page`. Per-image outcomes are surfaced through
a reporter/callback so the CLI can summarize.

A small archive helper exposes the on-disk size:

```python
# archive.py
def page_size(self, root_id: str, page_key: str) -> int | None:
    path = self._page_dir(root_id) / page_key
    return path.stat().st_size if path.exists() else None
```

### Component 3 — `_extract(..., refresh=False)`

`src/vtextract/cli.py`:

- When `refresh` is true, skip the `is_resource_complete` short-circuit so
  archived resources are reprocessed.
- Create the run-scoped `verified: set[str]` and pass it (with `refresh`) into
  `fetch_resource`.
- Accumulate per-image outcomes (ok / redownloaded-mismatch / downloaded-missing
  / unverified) and the list of mismatched + unverified page paths for the
  end-of-run summary.

### Component 4 — CLI surface

- `search` and `get`: add `--refresh` (store_true, default off), passed to
  `_extract`. Identical behavior, scoped to the command's hits.
- New `refresh` subcommand (`_run_refresh`):
  1. Resolve archive (`--out` or config), require credentials (like the others).
  2. Enumerate `archive/items/*/metadata.json`; build hits
     `[{"isadgID": int(dir_name)} for each]`. (The directory name is the
     isadgID; an item with an unparseable dir name is skipped with a warning.)
  3. **Confirmation gate**: print the item count and a warning that this makes
     many requests against the shared server, then prompt `Continue? [y/N]`.
     Proceed only on `y`/`yes` (case-insensitive). `-y/--yes` skips the prompt.
     If stdin is not a TTY and `--yes` was not given, abort with a message
     telling the user to pass `--yes` (rather than hanging).
  4. Run `_extract(refresh=True)` once over all hits.
  - Honors `--out`, `--config`, `--context-pages` (default 1, as `get`).
- **End-of-run summary** (all three paths, when `refresh` is active): counts of
  verified-OK / re-downloaded (mismatch) / downloaded (missing) / unverified,
  followed by the list of mismatched and unverified page file paths so
  "possibly corrupted" files are visible.

### Test seam

`refresh` and the `--refresh` flags use the same `_make_transport()` seam already
used by `search`/`get` (returns `None` in prod; tests inject an
`httpx.MockTransport`). The confirmation prompt reads via a thin indirection
(e.g. `input`) that tests drive with `--yes` or by monkeypatching, so no test
blocks on stdin.

## Data flow (refresh of one item)

1. `_extract` builds/forwards the hit; (refresh) does not skip on completeness.
2. `fetch_resource` fetches detail (by id) → manifest → writes item record +
   (via `_context_for`) `volume.json`.
3. For each primary + context page: `_ensure_page` HEAD-verifies the image.
   - ok / unverified → no download.
   - mismatch / missing → re-download image + annotation text, update state.
4. Resource re-marked complete; state saved.
5. After the loop, the CLI prints the verification summary.

## Error handling

- Per-item exceptions remain isolated by `_extract`'s existing try/except (one
  bad item does not stop the run).
- Per-page HEAD errors / missing `Content-Length` are caught inside
  `_ensure_page` → recorded as "unverified", file untouched.
- Confirmation gate + `--yes` + the non-TTY abort prevent accidental costly runs.

## Testing (TDD, MockTransport + committed fixtures, no network)

- **client:** `head` returns the `Content-Length` int; returns `None` when the
  header is absent; retries on a `503` then succeeds.
- **archive:** `page_size` returns the byte size for an existing page, `None`
  when missing.
- **fetcher (refresh):** size match → exactly one HEAD and zero GET for that
  image (request-counting handler); size mismatch → image re-downloaded and
  `_state.json` size/sha updated; missing file → downloaded; HEAD raises →
  outcome "unverified" and file left untouched; a page shared by two items is
  HEAD-checked once (verified-set dedup).
- **_extract (refresh):** an already-complete resource is reprocessed (not
  skipped) when `refresh=True`, and still skipped when `refresh=False`.
- **cli:** `refresh` declined at the prompt aborts with no requests; `--yes`
  proceeds; non-TTY without `--yes` aborts with guidance; item enumeration
  covers `items/*/metadata.json`. `get --refresh` and `search --refresh` thread
  the flag into `_extract`. The summary lists mismatched/unverified paths.

## Files touched

- `src/vtextract/client.py` — add `head`.
- `src/vtextract/archive.py` — add `page_size`.
- `src/vtextract/fetcher.py` — `refresh`/verified-set params; verify-or-redownload
  in `_ensure_page`; per-image outcome reporting.
- `src/vtextract/cli.py` — `--refresh` on `search`/`get`; new `refresh`
  subcommand with confirmation + `--yes`; refresh threading in `_extract`;
  end-of-run summary.
- `src/vtextract/progress.py` (or the `Reporter`) — verification-outcome
  counters + summary rendering (extent confirmed during planning).
- Tests alongside each.
