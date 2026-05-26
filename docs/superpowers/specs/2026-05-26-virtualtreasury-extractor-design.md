# Virtual Treasury Extractor — Design

**Date:** 2026-05-26
**Status:** Draft for review

## Purpose

A command-line tool that takes one or more searches against
[virtualtreasury.ie](https://virtualtreasury.ie) (the Virtual Record Treasury
of Ireland / "Beyond 2022" project) and downloads every matching resource —
full-resolution images, structured metadata, and transcription text — into an
organized, resumable local archive.

The public site is an Angular single-page app; both its `/search-results` and
`/item/<reference-code>` URLs are client-side routes that render an empty shell
to `curl`. All data is loaded by JavaScript from a separate backend. This tool
replicates the requests the browser makes.

## How the site actually works (reverse-engineered)

Backend host (from the app's `main.js` bundle): `https://by2022-prod.adaptcentre.ie`
(referred to below as `DCI`). All response samples that informed this spec are
committed under `docs/examples/` (`search/` for `doc_search`, `item/` for the
full per-item fan-out including subfolders for each API call).

| Purpose | Endpoint |
|---|---|
| **Search** | `POST {DCI}/IR_REST_V2/webapi/doc_search` |
| **Item metadata** (DSpace-style REST) | `GET {DCI}/rest/isadg-identity-statements/{isadgID}` |
| **IIIF manifest** (image + transcription enumeration) | `GET {DCI}/iiif/v1/{isadgID}/manifest` |
| **IIIF annotation list** (transcription) | `GET {DCI}/iiif/v1/{parentId}/list/{n}` (URL taken from the manifest) |
| **Image bytes** (Loris IIIF Image API, level 2) | `GET {DCI}/loris/{filename}/full/full/0/default.jpg` (URL taken from the manifest) |

The viewer also calls `parent`, `children`, `internal-links/summary`,
`kglinks/searchByIsadgId`, and `document-repository`. These drive UI
breadcrumbs and the knowledge graph and are **not needed** for the archive.

### Authentication

Every backend call carries a hardcoded HTTP Basic `Authorization` header,
embedded in the public JS bundle (decodes to a shared `glauco:…` credential).
The tool sends the same header the browser sends. This is a **shared
credential, not a personal one**, and the site has terms of use; the tool must
behave as a polite client (rate-limiting, retries with backoff, honest
`User-Agent`). The credential is read from configuration (env var or config
file), **not** hardcoded in our source, so it can be rotated without a code
change.

### Search request

- Method: `POST`, `Content-Type: application/json`.
- Body: `{ "indexDBName": "beyond_2022", ...query }` where `query` is the set of
  parameters visible in the `/search-results` URL (`kwList`, `kwOperList`,
  `searchContentDate_begin`/`_end`, `kwSearchFieldList`, `resultSorting`,
  `pageNumberInt`, `totalElementsInt`, etc.).
- Pagination: request with `pageNumberInt` (0-based) and `totalElementsInt`
  (page size). Response reports `generalInfo.totalDocs`,
  `generalInfo.docNumberPerPage`, and `generalInfo.currentPage`; iterate pages
  until all `totalDocs` records are retrieved.

### Search response shape (confirmed from a live sample)

```
{
  "generalInfo": {
    "totalDocs": 109,
    "docNumberPerPage": 100,
    "currentPage": 1,
    "facets": { ... }            // counts by year/collection/repository/etc.
  },
  "resultInfoList": [ { ...record... }, ... ]
}
```

Each record carries rich ISAD(G) metadata. Fields the tool uses:

- **`isadgID`** (integer) — the stable per-item identifier and the key for
  every subsequent call and for the on-disk layout.
- `displayReferenceCode` / `referenceCode[]`, `displayTitle`, `title[]`,
  dates, `documentRepository`, `creatorName[]`, `scopeAndContent[]`,
  `thematicCollection[]`, etc. — saved as the search-side metadata.
- `hasImages`, `hasTranscriptions` — **hints only.** The IIIF manifest is the
  source of truth for what images and transcriptions actually exist (a sample
  item had `hasTranscription: false` in its detail record yet a populated
  transcription annotation list in its manifest).
- `highLightFragments` — search-match snippets only; not the transcription.

### Per-item retrieval (confirmed from `docs/examples/item`)

Given an `isadgID` from a search hit, the tool makes three calls:

1. **Detail metadata** — `GET {DCI}/rest/isadg-identity-statements/{isadgID}`.
   Returns the full nested ISAD(G) record: `preferredTitle`,
   `preferredReferenceCode`, `isadgDates`, `isadgContexts` (creators, archival
   history), `documentRepository`, `extentAndMedium`, language, substitute
   source grades/formats, `thumbnail`, `numChildren`, `hasImageSequence`, etc.

2. **IIIF manifest** — `GET {DCI}/iiif/v1/{isadgID}/manifest`. A IIIF
   Presentation API 2 manifest. `sequences[].canvases[]` enumerates pages; for
   each canvas:
   - `images[].resource.@id` is the full-resolution image URL
     (`{DCI}/loris/{filename}/full/full/0/default.jpg`). The tool downloads
     this URL verbatim — it does not construct image URLs.
   - `otherContent[].@id` (when present) is a transcription annotation list.

3. **Transcription** — for each annotation-list URL in the manifest,
   `GET` it; `resources[]` are ordered `cnt:ContentAsText` fragments
   (`resource.chars`) each anchored to canvas coordinates (`on: …#xywh=…`).
   Concatenating `chars` in document order reconstructs the page text.

If the manifest has no canvases, the item has no images (handled gracefully);
if a canvas has no `otherContent`, it has no transcription.

## Architecture

A Python CLI package, layered so each unit has one purpose and is testable in
isolation:

1. **`client`** — thin HTTP layer over the backend. Owns base URL, the auth
   header (from config), a polite rate limiter (configurable delay +
   concurrency cap), and retry-with-backoff on 429/5xx. Single choke point for
   every request; nothing else makes raw HTTP calls.
2. **`search`** — builds the `doc_search` POST body from either a pasted
   `search-results` URL or explicit flags; handles pagination; yields raw
   result records.
3. **`schema`** — pure functions, no I/O. Maps a raw search record + detail
   record into a normalized `Record` (isadgID, reference code, title, dates,
   repository, raw blobs), and parses a manifest into a list of
   `(image_url, annotation_list_urls)` per canvas. Parses annotation lists into
   ordered text.
4. **`fetcher`** — orchestrates per-item retrieval using `client`: fetch detail
   metadata, fetch manifest, download each canvas image, fetch + reconstruct
   transcriptions; hands results to `archive` for writing.
5. **`archive`** — on-disk layout + `_state.json` run-state: dedup by
   `isadgID`, skip already-completed items, record per-item status and image
   checksums, record which search(es) produced each item, enabling resume
   across runs and across different searches.
6. **`cli`** — argument parsing; wires the pipeline together; progress output.

### On-disk layout

```
archive/
  _state.json                      # resume index: isadgID -> status, checksums, source searches
  474234/                          # one directory per item, keyed by isadgID
    metadata.json                  # normalized fields + raw search hit + raw detail record
    manifest.json                  # raw IIIF manifest (re-download source of truth)
    transcription.txt              # reconstructed text (concatenated chars), when present
    transcription.json             # raw annotation fragments with coordinates, when present
    images/
      0001.jpg                     # one file per canvas, in manifest order
      0002.jpg
      ...
```

### Data flow

1. `cli` parses the search (URL or flags) and output dir.
2. `search` pages through `doc_search`, yielding records.
3. For each record: `archive` checks `_state.json` (skip if already
   `complete`) → `fetcher` fetches detail metadata + manifest, downloads canvas
   images, fetches and reconstructs transcriptions → `schema` normalizes →
   `archive` writes files and marks the item `complete` with image checksums
   and the originating search.
4. Interruptible at any point; re-running any search resumes and never
   re-downloads completed items.

### Error handling

- Per-item failures are caught, logged, and recorded in `_state.json` as
  `failed` with a reason; the run continues. A later run retries only `failed`
  / incomplete items.
- A missing manifest or empty canvas list is normal (not all items have
  images) — recorded as `complete` with zero images, not as a failure.
- Transport errors get bounded retries with exponential backoff inside
  `client`.
- Image integrity verified by checksum recorded in `_state.json`; a partial
  image (size/checksum mismatch on resume) is re-fetched.
- Rate-limiting is on by default.

### Testing

- Fixtures are the committed samples in `docs/examples/` (search response and
  the full item fan-out). No test hits the live site or uses the real
  credential.
- `schema`: search+detail normalization, manifest → image/annotation parsing,
  annotation-list → text reconstruction, against the fixtures.
- `search`: body construction and pagination.
- `archive`: resume / dedup / state-transition / checksum logic on a temp dir.
- `client`: retry/backoff and rate-limit behavior against a stub server.

## Build sequence

1. `client` (auth from config, rate limit, retry).
2. `search` (URL parsing, body, pagination).
3. `schema` (normalization + manifest/annotation parsing) — fully specified by
   the committed fixtures.
4. `fetcher` (detail + manifest + image download + transcription).
5. `archive` (state file, resume, dedup, checksums).
6. `cli` (wire-up, progress, config).

## Tech stack

Python. HTTP via `httpx` (timeouts, retries, optional concurrency); CLI via
`argparse` or `click`; standard `json`/`pathlib`/`hashlib` for I/O. Dependencies
kept minimal.

## Out of scope (YAGNI)

- Full-collection crawl independent of searches.
- The viewer's `parent` / `children` / `summary` / knowledge-graph / repository
  calls (UI extras).
- Re-OCR or image processing/derivatives.
- A GUI or web interface.
- Resolving knowledge-graph (`kg_uri`) or external `findingAids` links.
