# Virtual Treasury Extractor — Design

**Date:** 2026-05-26
**Status:** Draft for review

## Purpose

A command-line tool that takes one or more searches against
[virtualtreasury.ie](https://virtualtreasury.ie) (the Virtual Record Treasury
of Ireland / "Beyond 2022" project) and downloads every matching resource —
full-resolution images, structured metadata, and transcription text — into an
organized, resumable local archive.

The public site is an Angular single-page app; its `/search-results` URL is a
client-side route that renders nothing useful to `curl`. All data is loaded by
JavaScript from a separate backend. This tool replicates the requests the
browser makes.

## How the site actually works (reverse-engineered)

Backend host (from the app's `main.js` bundle): `https://by2022-prod.adaptcentre.ie`
(referred to below as `DCI`).

| Purpose | Endpoint |
|---|---|
| **Search** | `POST {DCI}/IR_REST_V2/webapi/doc_search` |
| Item / metadata (DSpace REST) | `GET {DCI}/rest/<path>` |
| IIIF image delivery | `{DCI}/iiif/v1/...` |
| ARK identifier map (static JSON, on WordPress) | `{WORDPRESS}/cms/wp-content/uploads/json/ark-endpoints-reduced.json` |

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

Each record in `resultInfoList` already contains rich ISAD(G) metadata. Fields
the tool relies on:

- **`isadgID`** (integer) — the stable per-item identifier; the archive keys
  off this. (There is no ARK or manifest URL in the search response.)
- `hasImages` (bool), `hasTranscriptions` (bool) — whether to attempt image /
  transcription fetches for this record.
- `thumbnailImage` (string filename, may be `null`) — a hint at the IIIF
  identifier, not a full page list.
- Descriptive fields saved verbatim: `displayTitle`, `title[]`,
  `displayReferenceCode`, `referenceCode[]`, `documentRepository`,
  `documentRepositoryName`, `creator[]`, `creatorName[]`, `contentDate`,
  `createdDate`, `contentYears[]`, `scopeAndContent[]`, `archivalHistory[]`,
  `archivistsNote[]`, `thematicCollection[]`, `sourceFormat[]`,
  `sourceGrade[]`, `linkType[]`, plus the rest of the record.
- `highLightFragments` — search-match snippets only; **not** the full
  transcription.

### Open discovery item (Phase 0)

The search response does **not** tell us how to enumerate an item's image pages
or fetch its full transcription. Both require the per-item detail request(s)
the frontend fires when a single result is opened — most likely
`GET {DCI}/rest/...` keyed by `isadgID`, and/or a IIIF manifest. Phase 0 of
implementation captures one such request/response from browser DevTools and
locks down:

1. the exact URL/shape to resolve `isadgID` → full image list (IIIF image
   identifiers or manifest), and
2. where the full transcription text comes from.

The architecture isolates this in the `schema` and `fetcher` modules so the
rest of the tool is unaffected by what we find.

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
3. **`schema`** — pure functions mapping raw `doc_search` records (and the
   Phase 0 detail/manifest responses) into our internal `Record` type
   (`isadgID`, title, reference code, dates, repository, image identifiers,
   transcription, raw blob). The one module finalized after Phase 0. No I/O.
4. **`fetcher`** — given a `Record`, downloads full-resolution images (IIIF
   `full/max`), writes `metadata.json` and `transcription.txt`. Skips image /
   transcription work when `hasImages` / `hasTranscriptions` is false.
5. **`archive`** — on-disk layout + `_state.json` run-state: dedup by
   `isadgID`, skip already-completed items, record per-item status and image
   checksums, enabling resume across runs and across different searches.
6. **`cli`** — argument parsing; wires the pipeline together; progress output.

### On-disk layout

```
archive/
  _state.json                      # resume index: isadgID -> status, checksums, source searches
  474234/                          # one directory per item, keyed by isadgID
    metadata.json                  # normalized record + raw search hit (+ detail record)
    transcription.txt              # when hasTranscriptions
    images/
      0001.jpg
      0002.jpg
      ...
```

### Data flow

1. `cli` parses the search (URL or flags) and output dir.
2. `search` pages through `doc_search`, yielding records.
3. For each record: `schema` normalizes it → `archive` checks `_state.json`
   (skip if already `complete`) → `fetcher` resolves images/transcription
   (Phase 0 detail call as needed) and writes files → `archive` marks the item
   `complete` with checksums and notes which search(es) produced it.
4. Interruptible at any point; re-running any search resumes and never
   re-downloads completed items.

### Error handling

- Per-item failures are caught, logged, and recorded in `_state.json` as
  `failed` with a reason; the run continues. A later run retries only `failed`
  / incomplete items.
- Transport errors get bounded retries with exponential backoff inside
  `client`.
- Rate-limiting is on by default.

### Testing

- `schema`: unit tests against captured sample responses (the search sample
  already in hand, plus the Phase 0 detail sample) — no network.
- `search`: body construction and pagination, using recorded HTTP fixtures.
- `archive`: resume / dedup / state-transition logic on a temp directory.
- `client`: retry/backoff and rate-limit behavior against a stub server.
- No test requires the live site or the real credential.

## Build sequence

0. **Discovery (Phase 0):** capture one item-detail network exchange from
   DevTools; finalize `schema` + the `fetcher` image/transcription resolution.
1. `client` (auth from config, rate limit, retry).
2. `search` (URL parsing, body, pagination).
3. `fetcher` (IIIF image download, transcription, metadata write).
4. `archive` (state file, resume, dedup).
5. `cli` (wire-up, progress, config).

## Tech stack

Python. HTTP via `httpx` (timeouts, retries, optional concurrency); CLI via
`argparse` or `click`; standard `json`/`pathlib` for I/O. Dependencies kept
minimal.

## Out of scope (YAGNI)

- Full-collection crawl independent of searches.
- Re-OCR or image processing/derivatives.
- A GUI or web interface.
- Resolving the knowledge-graph (`kg_uri`) or external `findingAids` links.
