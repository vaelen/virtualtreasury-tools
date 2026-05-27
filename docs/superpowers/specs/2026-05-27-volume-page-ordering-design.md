# Volume page ordering + `vtindex page` — design

**Date:** 2026-05-27
**Status:** approved, pending implementation

## Problem

Given a single page file in the archive — e.g.
`pages/504339/sp063-356-000_0076_74.jpg` — there is no way to find the next or
previous page in the volume. The only record of page order is the volume's IIIF
manifest (`sequences[0].canvases`, an ordered list). The per-page `.json`
(transcription annotation list) and `volume.json` carry no ordering, and the
image filename's numeric suffix is **not** a reliable sort key (the two embedded
numbers count different things). Today answering "what's next/previous" means
re-reading and traversing the manifest by hand.

Two gaps compound this:

1. `volume.json` is a *derived* file we write (`schema.volume_info` →
   `archive.write_volume_info`), currently holding only `label` and
   `reference_code` — both of which, for a true multi-page volume, are just the
   shelfmark. The full ordered canvas list is fetched at write time
   (`fetcher._context_for`) and then discarded.
2. The index's `page` table is `(root_id, page_key, has_text)` with no ordering,
   and it is populated **only** from transcription files (`*.jpg.txt`), so pages
   without a transcription are never indexed at all.

## Goals

- **Change 1:** `volume.json` records the volume's pages in order, plus a
  descriptive `title` for the volume.
- **Change 2:** the index stores page ordinals (and gains complete page
  coverage), and a new `vtindex page` command prints a page's previous / current
  / next neighbours with their file paths.

## Non-goals

- Offline backfill of existing archives. Existing `volume.json` files predate
  the new fields; they are refreshed by re-running extraction with
  `--context-pages >= 1` (images already present are skipped; manifests are
  re-fetched). The index degrades gracefully on volume.json that lacks the new
  fields.
- Changing *when* `volume.json` is written (still only on `--context-pages >= 1`).
- Resource-level page ordering (ordering is a property of the physical volume).

## Domain facts established during design

- The **volume manifest** (the multi-page root) has no descriptive title: its
  top-level `label`, its `Title` metadata entry, and its `ReferenceCode` are all
  the same shelfmark string (e.g. `"TNA SP 63/356"`). A descriptive title
  (e.g. `"Letters, Papers, Correspondence: 1694"`) exists only at the **item**
  level, in the root resource's identity-statement detail
  (`preferredTitle.title`). The root resource is the item whose
  `isadgID == rootID`.
- A canvas's image filename — the on-disk `page_key` — is embedded in
  `images[0].resource["@id"]` as `…/loris/<filename>/full/full/0/default.jpg`.
- `fetcher._context_for` already fetches `/iiif/v1/{root_id}/manifest` on a
  cache miss; producing the ordered page list there is free.

## Change 1 — `volume.json` gains `pages` and `title`

Existing `label` and `reference_code` are unchanged. New shape:

```json
{
  "label": "TNA SP 63/356",
  "reference_code": "TNA SP 63/356",
  "title": "Letters, Papers, Correspondence: 1694",
  "pages": [
    {"page_key": "sp063-356-000_0075_73.jpg", "label": "TNA SP 63/356/29", "canvas_id": ".../canvas/p351824"},
    {"page_key": "sp063-356-000_0076_74.jpg", "label": "TNA SP 63/356/29", "canvas_id": ".../canvas/p351825"}
  ]
}
```

### `schema.py` (pure, no I/O)

- New `canvas_page_key(canvas) -> str | None`: extract the Loris filename from
  `images[0].resource["@id"]` by splitting on `/loris/` and taking the segment
  before the next `/`. Returns `None` for a canvas without a parseable image.
- New `detail_title(detail) -> str`: `(detail.get("preferredTitle") or {}).get("title") or ""`
  (the same extraction `normalize_record` uses).
- `volume_info(manifest, *, title=None)` extends its returned dict:
  - `pages`: one entry per canvas in `manifest["sequences"][0]["canvases"]`, in
    sequence order, shaped `{"page_key", "label", "canvas_id"}`. Canvases where
    `canvas_page_key` returns `None` are skipped defensively.
    `label` is the canvas `label`; `canvas_id` is the canvas `@id`.
  - `title`: the value of the `title` argument (omitted/`null` when not provided).
  - `label` and `reference_code` unchanged.

### `fetcher.py` (I/O lives here)

In `_context_for`, on the volume-manifest cache miss:

1. Fetch the volume manifest (as today).
2. Additionally `GET /rest/isadg-identity-statements/{root_id}` and apply
   `detail_title` to get the volume's descriptive title.
3. Call `volume_info(root_manifest, title=<that title>)` and write it.

The root detail is fetched once per volume (not per page) and cached alongside
the manifest. If the call fails or the root has no catalogue entry, `title` is
`None` and the manifest/`pages` are written regardless — `root_title` resolution
never blocks the volume record.

`archive.write_volume_info` is unchanged (it dumps whatever dict it is given).

## Change 2 — index ordering + `vtindex page`

### Schema (`index/db.py` `_DDL`), with a schema-version bump

```sql
CREATE TABLE volume (root_id TEXT PRIMARY KEY, label TEXT, reference_code TEXT, title TEXT);
CREATE TABLE page (
    root_id TEXT, page_key TEXT, ordinal INTEGER, label TEXT, has_text INTEGER,
    PRIMARY KEY (root_id, page_key)
);
```

Bumping the stored `schema_version` makes existing indexes raise the current
`SchemaMismatch`, prompting a `vtindex build --rebuild`.

### Two producers, neither clobbers the other's columns

Both write to `page` via `INSERT ... ON CONFLICT(root_id, page_key) DO UPDATE`
touching only their own columns:

- **Volume indexing** (`reader.read_volume` now also returns the ordered page
  list; `db.upsert_volume`) is authoritative for page **existence + ordinal +
  label**. For a given `root_id` it:
  1. clears `ordinal`/`label` for all pages of that root,
  2. upserts every listed page setting `ordinal` (1-based, sequence order) and
     `label`, inserting any not-yet-present page with `has_text = 0`,
  3. prunes volume-only rows (`has_text = 0`) for that root no longer in the
     list.
  This also fixes the prior gap: every page in the volume is now indexed, not
  only transcribed ones. The volume's `title` is stored on the `volume` row.
- **Transcription indexing** keeps owning `has_text = 1`, preserving any
  `ordinal`/`label` already set (which may be `NULL` if the volume has not been
  indexed yet).
- `db.delete_source` for a `volume` source clears `ordinal`/`label` for that
  root and drops its volume-only rows (transcription-backed rows survive).

### `reader` / models

- `VolumeRow` gains `title: str | None` and `pages: list[VolumePage]`, where
  `VolumePage` is `{page_key, label, ordinal}` (ordinal assigned 1-based from
  list position). `read_volume` populates both from `volume.json`; a
  `volume.json` lacking `pages` yields an empty list (graceful pre-migration
  behaviour). `db.upsert_volume(VolumeRow)` consumes `.title` for the `volume`
  row and `.pages` for the `page`-table writes described above.
- `VolumeInfo` (the `volumes` listing row) gains `title`.

### CLI — `vtindex page <root_id>/<page_key>`

- Parse the argument as `root_id/page_key`. Look up the page's `ordinal`, then
  fetch `ordinal - 1` and `ordinal + 1` within the same `root_id`.
- Default output: a small table with rows prev / current / next, columns
  ordinal, page_key, label, and resolved file paths (reusing `_page_dict` for
  image/metadata/transcription paths). The volume's `title` is shown in the
  header.
- `--json`: structured `{volume: {root_id, title}, previous, current, next}`
  where each page is the `_page_dict` shape plus `ordinal` and `label`; absent
  neighbours are `null`.
- Exit codes:
  - `0` — page found (including boundary pages with one neighbour).
  - `1` — page not in the index (mirrors `search`'s "no match").
  - `2` — usage/parse error (bad `root_id/page_key` form), via the existing
    `argparse`/error handling.
  - Page present but with no `ordinal` (volume.json predates Change 1): print the
    current page, warn on stderr that ordering is unavailable, exit `0`.

## Testing (TDD, against committed fixtures only — no network)

- **`schema`:** `volume_info` produces the ordered `pages` list from the manifest
  fixture and passes `title` through; `canvas_page_key` parsing and `None` on a
  canvas without an image; `detail_title` from an identity-statement fixture.
- **`fetcher`:** the root-detail fetch feeds `title` into the written
  `volume.json`; graceful fallback (manifest + `pages` still written, `title`
  null) when the identity-statement call fails.
- **`reader` / `db`:** volume page-list + `title` round-trip; the two-producer
  no-clobber invariant in both orders (volume-then-transcription and
  transcription-then-volume); prune on a shrunk page list; `delete_source` for a
  volume.
- **`cli`:** `page` mid-volume (prev + next), at the first/last page (one
  neighbour), not-found → exit 1, missing-ordinal → exit 0 + stderr warning, and
  the `--json` shape.

## Files touched

- `src/vtextract/schema.py` — `canvas_page_key`, `detail_title`, extend
  `volume_info`.
- `src/vtextract/fetcher.py` — fetch root detail, pass `title` to `volume_info`.
- `src/vtextract/index/db.py` — schema, version bump, `page`/`volume` upsert and
  delete logic.
- `src/vtextract/index/reader.py` — `read_volume` returns `title` + page list.
- `src/vtextract/index/models.py` — `VolumeRow.title`, `VolumeInfo.title`.
- `src/vtextract/index/builder.py` — pass the page list through volume indexing.
- `src/vtextract/index/cli.py` — `page` subcommand; `title` in `volumes` output.
- Tests alongside each.
