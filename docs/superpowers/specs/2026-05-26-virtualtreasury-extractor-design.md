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

## Core data model: resources vs physical pages

Two distinct things, in a many-to-many relationship:

- **Resource** — a catalogued intellectual entity, identified by `isadgID`.
  Searches return resources (e.g. *Will of MITCHELL, CALEB*, item 550,
  `isadgID 474234`).
- **Physical page** — an actual scanned image, identified by its Loris image
  identifier (a filename, e.g. `IMC_1954_RoD_1_Page_253.jpg`).

One physical page often carries several resources (item 550 *and* item 551,
*Will of HOUSTON, JOHN*, are both abstracted onto the same book page), and one
resource can span several pages. Crucially, **both the image bytes and the
transcription are page-level, not resource-level**: the transcription
annotation list is keyed to the canvas (physical page) and contains the OCR for
the whole page — every record on it, undivided. There is no reliable way to
split a page's transcription per resource.

Therefore the archive stores **pages once in a shared store**, grouped into a
folder per **volume** (the manifest-root item, identified by the `rootID`
embedded in each canvas `@id`) and keyed within it by Loris identifier,
deduplicated by identifier + checksum. Resources are represented as lightweight
records that reference the pages they span. This avoids duplicating images and
transcriptions across resources that share a page.

## How the site actually works (reverse-engineered)

Backend host (from the app's `main.js` bundle): `https://by2022-prod.adaptcentre.ie`
(referred to below as `DCI`). All response samples that informed this spec are
committed under `docs/examples/` (`doc-search/` for the search response,
`item/` for the full per-item fan-out, with a subfolder for each API call).

| Purpose | Endpoint |
|---|---|
| **Search** | `POST {DCI}/IR_REST_V2/webapi/doc_search` |
| **Item metadata** (DSpace-style REST) | `GET {DCI}/rest/isadg-identity-statements/{isadgID}` |
| **Item IIIF manifest** (the resource's own pages) | `GET {DCI}/iiif/v1/{isadgID}/manifest` |
| **Volume IIIF manifest** (full page sequence, for context pages) | `GET {DCI}/iiif/v1/{rootID}/manifest` |
| **IIIF annotation list** (page transcription) | `GET {DCI}/iiif/v1/{rootID}/list/{n}` (URL taken from the manifest) |
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

- **`isadgID`** (integer) — the resource identifier and the key for every
  subsequent call and for the on-disk `items/` layout.
- `displayReferenceCode` / `referenceCode[]`, `displayTitle`, `title[]`,
  dates, `documentRepository`, `creatorName[]`, `scopeAndContent[]`,
  `thematicCollection[]`, etc. — saved as the search-side metadata.
- `hasImages`, `hasTranscriptions` — **hints only.** The IIIF manifest is the
  source of truth for what images and transcriptions actually exist (a sample
  item had `hasTranscription: false` in its detail record yet a populated
  transcription annotation list in its manifest).
- `highLightFragments` — search-match snippets only; not the transcription.

### Per-item retrieval (confirmed from `docs/examples/item`)

Given an `isadgID` from a search hit:

1. **Detail metadata** — `GET {DCI}/rest/isadg-identity-statements/{isadgID}`.
   Full nested ISAD(G) record: `preferredTitle`, `preferredReferenceCode`,
   `isadgDates`, `isadgContexts` (creators, archival history),
   `documentRepository`, `extentAndMedium`, language, substitute source
   grades/formats, `thumbnail`, `numChildren`, `hasImageSequence`, etc.

2. **Item manifest** — `GET {DCI}/iiif/v1/{isadgID}/manifest` (IIIF
   Presentation API 2). `sequences[].canvases[]` enumerates the resource's own
   pages; for each canvas:
   - `images[].resource.@id` is the full-resolution image URL
     (`{DCI}/loris/{filename}/full/full/0/default.jpg`). The Loris `{filename}`
     is the page identifier and the page-store key. The tool downloads the URL
     verbatim — it does not construct image URLs.
   - `otherContent[].@id` (when present) is the page's transcription annotation
     list.
   - the canvas `@id` embeds the **volume manifest-root id**
     (`…/iiif/v1/{rootID}/canvas/…`), used for context pages.

3. **Transcription** — for each annotation-list URL, `GET` it; `resources[]`
   are ordered `cnt:ContentAsText` fragments (`resource.chars`) anchored to
   canvas coordinates (`on: …#xywh=…`). Concatenating `chars` in order
   reconstructs the page text. (This text covers the whole physical page, i.e.
   all resources on it.)

4. **Context pages** (default ±1, configurable) — extract `rootID` from a
   canvas `@id`, `GET {DCI}/iiif/v1/{rootID}/manifest` (cached per `rootID` per
   run, since many hits share a volume), locate the resource's canvas in the
   root sequence, and pull the N preceding and N following canvases' images and
   annotation lists into the shared page store. This catches records that spill
   across a page boundary. Volume edges simply yield fewer pages.

If the item manifest has no canvases, the resource has no images (handled
gracefully). If a canvas has no `otherContent`, that page has no transcription.

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
3. **`schema`** — pure functions, no I/O. Normalizes a search record + detail
   record into a `Record`; parses a manifest into per-canvas `Page` descriptors
   (page key/Loris filename, image URL, annotation-list URLs, `rootID`, canvas
   id, dimensions); reconstructs annotation-list JSON into ordered page text.
4. **`fetcher`** — orchestrates per-resource retrieval via `client`: detail
   metadata, item manifest, then for each page (primary, plus ±N context pages
   from the cached root manifest) ensure the page exists in the store. Returns
   the resource's ordered page list (primary/context tags) to `archive`.
5. **`archive`** — owns the shared page store and the resource records.
   Stores pages under `pages/{rootID}/`, one folder per volume; deduplicates
   pages by Loris identifier (+ checksum); writes page image/transcription
   files once and a `volume.json` per volume when available; writes per-resource
   `metadata.json` + `manifest.json` with an ordered `pages[]` reference list;
   maintains `_state.json` (per-resource and per-page status, checksums,
   originating searches) for resume/dedup across runs and searches.
6. **`cli`** — argument parsing (including `--context-pages N`, default 1);
   wires the pipeline together; progress output.

### On-disk layout

```
archive/
  _state.json                          # resume index: resources + pages, status, checksums, source searches
  pages/                               # shared page store, one folder per volume (manifest-root id)
    208925/                            # volume: "Registry of Deeds... abstracts of wills, vol 1: 1708-45"
      volume.json                      # volume label + reference code (when the root manifest is available)
      IMC_1954_RoD_1_Page_253.jpg      # full-resolution image, keyed by Loris identifier
      IMC_1954_RoD_1_Page_253.jpg.txt  # reconstructed page transcription (all records on the page)
      IMC_1954_RoD_1_Page_253.jpg.json # raw annotation fragments with coordinates
  items/                               # one directory per resource (isadgID)
    474234/                            # Will of MITCHELL, CALEB
      metadata.json                    # normalized fields + raw search hit + raw detail record + ordered pages[]
      manifest.json                    # raw item IIIF manifest
    474235/                            # Will of HOUSTON, JOHN — references the same page, no re-download
      metadata.json
      manifest.json
```

Each `metadata.json` `pages[]` entry records: page key (Loris filename),
volume id (`rootID`), role (`primary`/`context`), relative path into
`pages/{rootID}/`, canvas label, and dimensions. `volume.json` is written when
the volume's root manifest has been fetched (always the case when context-page
fetching is enabled).

### Data flow

1. `cli` parses the search(es) (URL or flags), output dir, and context depth.
2. `search` pages through `doc_search`, yielding resource records.
3. For each record: `archive` checks `_state.json` (skip if `complete`) →
   `fetcher` fetches detail + item manifest, determines primary pages, and via
   the cached root manifest determines ±N context pages → for each page not
   already in the store, downloads image + annotation list → `schema`
   normalizes record and reconstructs page text → `archive` writes any new
   page files, writes the resource's `metadata.json`/`manifest.json`, and marks
   the resource `complete` with its page list and originating search.
4. Interruptible at any point; re-running any search resumes and re-downloads
   neither completed resources nor already-stored pages.

### Error handling

- Per-resource failures are caught, logged, and recorded in `_state.json` as
  `failed` with a reason; the run continues. A later run retries only `failed`
  / incomplete resources.
- A missing item manifest or empty canvas list is normal (not all resources
  have images) — recorded as `complete` with zero pages, not a failure.
- Volume edges (no prev/next canvas) yield fewer context pages, not an error.
- Transport errors get bounded retries with exponential backoff inside
  `client`.
- Page integrity verified by checksum in `_state.json`; a partial/mismatched
  page on resume is re-fetched.
- Rate-limiting is on by default.

### Testing

- Fixtures are the committed samples in `docs/examples/`. No test hits the live
  site or uses the real credential.
- `schema`: search+detail normalization; manifest → page descriptors incl.
  `rootID` extraction from canvas `@id`; annotation-list → ordered text.
- `search`: body construction and pagination.
- `archive`: global page dedup (two resources sharing a page store one copy);
  resume / state transitions / checksum logic on a temp dir.
- `fetcher`: context-page selection from a root-manifest sequence (including
  volume edges) with a stubbed `client`.
- `client`: retry/backoff and rate-limit behavior against a stub server.

## Build sequence

1. `client` (auth from config, rate limit, retry).
2. `search` (URL parsing, body, pagination).
3. `schema` (normalization + manifest/annotation/`rootID` parsing) — fully
   specified by the committed fixtures.
4. `archive` (shared page store, dedup, resource records, `_state.json`).
5. `fetcher` (detail + item manifest + primary pages + ±N context pages via
   cached root manifest).
6. `cli` (wire-up, `--context-pages`, progress, config).

## Tech stack

Python. HTTP via `httpx` (timeouts, retries, optional concurrency); CLI via
`argparse` or `click`; standard `json`/`pathlib`/`hashlib` for I/O. Dependencies
kept minimal.

## Out of scope (YAGNI)

- Full-collection crawl independent of searches.
- The viewer's `parent` / `children` / `summary` / knowledge-graph / repository
  calls (UI extras).
- Splitting a page's transcription per resource (the data does not support it).
- Re-OCR or image processing/derivatives.
- A GUI or web interface.
- Resolving knowledge-graph (`kg_uri`) or external `findingAids` links.
