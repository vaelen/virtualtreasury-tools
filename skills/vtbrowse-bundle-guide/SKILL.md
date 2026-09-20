---
name: vtbrowse-bundle-guide
description: >-
  Explains how to navigate, read, and parse a Bundle exported from the
  `vtbrowse` TUI (part of vtextract / Virtual Record Treasury of Ireland).
  Use this whenever someone has an exported bundle folder, .zip, or .tar.gz
  and asks what its files mean, how to read `bundle.json` / `volume.json` /
  the per-page `.txt` / `.json` / `.names.json` / `.notes.md` files, where
  the transcriptions, extracted people, human notes, or images are, what
  "context pages" are, how `page_key` maps to files, or how to
  turn the bundle into something else (a document, a dataset, a script that
  walks it). Trigger even when they don't say "vtbrowse" by name but clearly
  describe a folder of per-volume subfolders containing `bundle.json`,
  `volume.json`, and `.jpg.txt` transcription files.
---

# Navigating a `vtbrowse` Bundle Export

A **Bundle** is a curated selection of physical manuscript pages a user
assembled in the `vtbrowse` TUI. Exporting it (the `x` key) writes a
self-contained, plain-file deliverable: per-volume folders of transcriptions,
page metadata, and (optionally) page images, plus a top-level `bundle.json`
that records the curation. The export draws entirely from a local `vtextract`
archive — there is no live API in an export; everything is already on disk.

Use this skill to read or process an export accurately. The field names and
behaviours below match the code exactly — prefer them over guessing.

## Layout

An export is a folder (or the same tree inside a `.zip` / `.tar.gz`):

```
<bundle_root>/
├── <root_id>/                  # one folder per volume, named by its volume id
│   ├── volume.json             # volume metadata (always written; {} if unknown)
│   ├── <page_key>.txt          # page transcription, plain text  (only if it exists)
│   ├── <page_key>.json         # raw IIIF annotation list        (only if it exists)
│   ├── <page_key>.names.json   # people extracted from the page   (only if it exists)
│   ├── <page_key>.notes.md     # hand-written notes for the LLM   (only if it exists)
│   └── <page_key>              # page image, no extra suffix      (only with images)
└── bundle.json                 # the selection manifest (always written)
```

Concrete example (volume id `474234`, page keys end in `.jpg`):

```
my_bundle/
├── 474234/
│   ├── volume.json
│   ├── 474234_Page_003.jpg.txt        # transcription text
│   ├── 474234_Page_003.jpg.json       # source annotation list
│   ├── 474234_Page_003.jpg.names.json # people extracted from the page
│   ├── 474234_Page_003.jpg.notes.md   # a human's notes about the page (rare)
│   ├── 474234_Page_003.jpg            # the image itself (only if exported --images)
│   ├── 474234_Page_004.jpg.txt
│   └── 474234_Page_004.jpg.json
└── bundle.json
```

**The crucial naming rule:** a `page_key` already includes the image extension
(e.g. `474234_Page_003.jpg`). So for one page you get:

- transcription → `<page_key>.txt`  → `474234_Page_003.jpg.txt`
- annotation list → `<page_key>.json` → `474234_Page_003.jpg.json`
- extracted people → `<page_key>.names.json` → `474234_Page_003.jpg.names.json`
- human notes → `<page_key>.notes.md` → `474234_Page_003.jpg.notes.md`
- image → `<page_key>` (no added suffix) → `474234_Page_003.jpg`

The image file and the `.txt`/`.json` share the same stem; only the image lacks
a trailing `.txt`/`.json`. Don't assume `.json` is "the image's sidecar" — it is
the transcription source. Strip nothing; match on the full `page_key`.

## The domain model (read this before interpreting anything)

These distinctions are non-obvious and change how you read the files:

- A **resource** (`isadg_id`, an integer) is a *catalogued entity* — a deed, a
  petition, a memorial. It is what a search returns.
- A **physical page** (`page_key`) is one scanned image leaf.
- The relationship is **many-to-many**: one page can carry several resources;
  one resource can span several pages.
- Therefore **both the transcription and the image are page-level, not
  resource-level.** A `<page_key>.txt` is the transcription of the *whole
  physical page* — every record printed on that leaf — and cannot be cleanly
  split per resource. Don't claim a transcription "is the text of resource N";
  it is the text of the page that resource N appears on.
- A **volume** (`root_id`) groups pages. Pages are stored once per volume and
  referenced by resources, which is why the export is organised by volume folder
  rather than by resource.

## `bundle.json` — the selection manifest

Records *what the user chose* and lets the curation be reopened in `vtbrowse`
(against the original archive). Shape:

```json
{
  "version": 1,
  "created_at": "2026-05-30T14:22:05.123456+00:00",
  "selected_items": [
    {
      "isadg_id": 474234,
      "matched_pages": [
        {"root_id": "474234", "page_key": "474234_Page_003.jpg"},
        {"root_id": "474234", "page_key": "474234_Page_004.jpg"}
      ]
    }
  ],
  "page_state": [
    {"root_id": "474234", "page_key": "474234_Page_009.jpg", "state": "include"},
    {"root_id": "474234", "page_key": "474234_Page_004.jpg", "state": "exclude"}
  ]
}
```

| Field | Meaning |
|---|---|
| `version` | Bundle format version (currently `1`). A reader should reject other values rather than guess. |
| `created_at` | UTC ISO-8601 timestamp of the save/export. |
| `selected_items[]` | Catalogued resources the user toggled in. |
| `selected_items[].isadg_id` | The resource's `isadgID`. Maps to `archive/items/<isadg_id>/` in the *source* archive, **not** to a folder in the export. |
| `selected_items[].matched_pages[]` | A **snapshot**, taken at selection time, of every page that resource contributed — the matched page *plus its context pages*. Each is `{root_id, page_key}`. The snapshot is deliberate: re-running the search later won't silently change a saved bundle. |
| `page_state[]` | Manual per-page overrides the user made by hand. |
| `page_state[].state` | `"include"` (force this page in, even if no selected item contributes it) or `"exclude"` (force it out, overriding any item that contributes it). |

**Computing what's actually in the bundle** (the "effective pages"), which is
exactly what got written to disk:

```
a page is in the bundle  ⇔
    (it appears in some selected_items[].matched_pages  OR  page_state == "include")
    AND  page_state != "exclude"
```

So `exclude` always wins, and `include` can add a page no item brought in. To
list the files an export *should* contain, compute this set; every member maps
to `<root_id>/<page_key>.{txt,json}` (and the image, if images were included).
Note a page can be in `matched_pages` yet absent from disk because `page_state`
later excluded it — trust the formula, not the raw `matched_pages` list.

## `volume.json` — per-volume metadata

One per volume folder. A snapshot of the volume taken from its IIIF manifest:

```json
{
  "label": "Registry of Deeds, Transcript Book 86",
  "reference_code": "IMC 1954/RoD/1/86",
  "title": "Registry of Deeds Transcript Book 86: memorials 1737",
  "pages": [
    {"page_key": "474234_Page_001.jpg", "label": "1", "canvas_id": "https://iiif.virtualtreasury.ie/iiif/v1/474234/canvas/1"},
    {"page_key": "474234_Page_002.jpg", "label": "2", "canvas_id": "https://iiif.virtualtreasury.ie/iiif/v1/474234/canvas/2"}
  ]
}
```

| Field | Meaning |
|---|---|
| `label` | The manifest label — usually the shelfmark / short title. |
| `reference_code` | The archival reference code, or `null` if the manifest had none. |
| `title` | The volume's full descriptive title, or `null`. |
| `pages[]` | **Every** page of the volume in sequence order — not just the bundled ones. Each entry is `{page_key, label, canvas_id}`. |

Two important uses of `pages[]`:

1. **Ordering.** The bundle's selected pages aren't inherently ordered; use this
   list to present them in original document sequence.
2. **Context vs. matched page** (see below) — the ordering reveals which bundled
   pages are neighbours of which.

If the volume's metadata was never captured during extraction (e.g. the archive
was built with `--context-pages 0`, which is what triggers the volume-manifest
fetch), `volume.json` is an empty object `{}`. Treat missing/empty gracefully.

## `<page_key>.txt` — the transcription

Plain text. It is the reconstruction of the page's transcription: each text
fragment from the page's IIIF annotation list, concatenated in document order
and joined with newlines.

What this means for a reader:

- It is **page-level**: the full text of that physical leaf, covering all
  records on it (see the domain model). It is not segmented per resource.
- **The text may contain HTML.** Fragments are stored verbatim from the source,
  whose `format` is often `text/html` (e.g. `<p>…</p>`). If you need clean prose,
  strip tags yourself; don't assume it's already plain.
- If a page had no transcription, there is **no `.txt` file** for it — its
  absence is normal, not corruption.

## `<page_key>.json` — the raw annotation list

The unmodified IIIF AnnotationList the `.txt` was derived from. Preserve it when
you need provenance the flattened text loses: per-fragment HTML, motivation, and
the exact canvas region each fragment annotates. Shape:

```json
{
  "@context": "http://iiif.io/api/presentation/2/context.json",
  "@id": "https://iiif.virtualtreasury.ie/iiif/v1/474234/list/3",
  "@type": "sc:AnnotationList",
  "resources": [
    {
      "@type": "oa:Annotation",
      "motivation": "oa:commenting",
      "resource": {
        "@type": "cnt:ContentAsText",
        "format": "text/html",
        "chars": "<p>To the right honourable Sir Constantine Phipps…</p>"
      },
      "on": "https://iiif.virtualtreasury.ie/iiif/v1/474234/canvas/3"
    }
  ]
}
```

- `resources[]` — the annotations, in order. The `.txt` is exactly
  `"\n".join(r.resource.chars for r in resources if chars present)`.
- `resource.chars` — one text fragment (possibly HTML).
- `resource.format` — MIME type of that fragment (`text/html` or `text/plain`).
- `on` — the IIIF canvas the fragment sits on (a `#xywh=` region may be
  appended, pinning it to a rectangle of the page image).

If a page had no annotation list, there is no `.json` for it.

## `<page_key>.notes.md` — a human's notes about the page

Free-form Markdown a person wrote about this physical page, copied verbatim
from the source archive. It is the one file in an export that is **human
authored**, not scraped or LLM-generated. Rare; absence is normal.

**Where it comes from.** The user writes it in `vtbrowse` (press `n` on a
page to open a notes editor beside the transcription; closing saves it) or by
hand at `archive/pages/<root_id>/<page_key>.notes.md`. Its purpose is to
steer LLM passes over the page — chiefly `vtextract names`, which sends the
notes to the model as a `NOTES` block that overrides its normal rules — but
it may hold any context the user knows: corrected readings, who an initial
or "Mrs X" refers to, that a capitalised word is a place or estate rather
than a person, cross-references to other pages.

**Precedence.** Notes are the user's own judgement and win over everything
else in the bundle:

- Over `.names.json`: the notes may have been written *after* the names pass
  ran — `.names.json` is only regenerated when the user re-runs
  `vtextract names --force` — so the two can disagree. When they do, the
  notes are right and `.names.json` is stale. Apply the notes yourself; do not
  assume the LLM output already reflects them.
- Over the `.txt` transcription where the note says a reading is wrong (a
  note like `"David Power" is a transcription error for Daniel Power`
  corrects the transcriber, not just the LLM).

**How to apply them when listing or indexing people** (do this before
presenting any people list for a page that has notes):

1. Start from `.names.json` `people[]` if present, else from the `.txt`.
2. For each correction in the notes, replace the canonical name but keep the
   on-page surface form(s) as aliases (`["Daniel Power", "David Power Gent"]`).
3. For each "not a person" note, drop that entry.
4. For each role or identity note (addressee, witness, "same man as page 41"),
   keep the person and carry the note as an annotation.
5. Say in your answer which entries the notes changed.

**Editing.** The copy in an export is inert: changing it does not update the
archive or re-run anything. To change what the LLM sees, edit the file in the
source archive (or in `vtbrowse`) and re-run `vtextract names <refcode>
--force`, then re-export.

## `<page_key>.names.json` — people extracted from the page

Written by the `vtextract names` LLM pass over the page's transcription and
copied into the export verbatim. Present only if that pass was run on the
source archive and succeeded for this page — absence is normal, not
corruption. Shape (sidecar schema 2):

```json
{
  "schema": 2,
  "model": "gemini/gemini-2.5-flash-lite",
  "people": [
    ["William Walker", "Mr. William Walker", "William Wal"],
    ["Patrick Kelly"]
  ],
  "elapsed_ms": 34884,
  "usage": {"in": 9932, "out": 20171, "total": 30103, "cached": 0}
}
```

- `people[]` — one entry per distinct person on the page. Each entry is a
  **compact array**: `[canonical, *surface_forms]`. The first element is the
  canonicalized name (coreference-merged and abbreviation-expanded, so it may
  not appear verbatim on the page); any further elements are the variant
  strings as actually written (`"Thos. Young"`, `"Mr. William Walker"`). A
  single-element entry means no on-page variant beyond the canonical was
  recorded.
- `schema` — check it equals `2` before parsing; older archives used a v1
  verbose-object form you should not expect in exports.
- `model`, `elapsed_ms`, `usage` — provenance of the extraction (which LLM,
  wall-clock, token counts). `usage` may be absent; treat it as optional.
- Like everything else, it is **page-level**: the people on that physical
  leaf, across all resources printed on it. Extraction is LLM output over
  often-difficult manuscript transcriptions — expect occasional
  misspellings, splits, or merges; don't treat it as authoritative ground
  truth.
- Source archives may also hold `<page_key>.names.error.json` files for pages
  whose extraction failed permanently; those are **not** exported.

## Images

- Present **only if the bundle was exported with images** *and* the source
  archive actually held the image bytes (images are opt-in throughout vtextract,
  via `--images`).
- The file is named exactly `<page_key>` — e.g. `474234_Page_003.jpg` — a normal
  JPEG. There is no separate manifest of images; their presence on disk is the
  signal.
- A metadata-only export still gives you full transcriptions and annotation
  JSON; only the image leaves are missing. To get them, the *source* archive
  must be re-fetched with `vtextract … --images` (resume-aware, so it backfills
  images for resources already pulled as metadata-only) and the bundle
  re-exported.

## Context pages (and an honest limitation)

When the archive was extracted with `--context-pages N`, each matched page was
captured together with up to `N` neighbouring pages on **each** side, so a
reader has surrounding context (a deed often spills across leaves). Those
neighbours are pulled into the bundle alongside the page that actually matched,
and they appear in `matched_pages` and as ordinary page files.

**The export does not label which page was the real match vs. a context
neighbour.** That distinction (a `role` of `"primary"` or `"context"`) lives in
the *source* archive's `items/<isadg_id>/metadata.json`, which is **not** copied
into the export. Within an export you have two practical options:

1. Treat each volume's bundled pages as a contiguous run of related leaves and
   read them in `volume.json` `pages[]` order — usually sufficient.
2. If you must recover primary-vs-context precisely, go back to the source
   archive's `items/<isadg_id>/metadata.json` (its `pages[]` carry the `role`).

Don't fabricate a `role` field for export files — it isn't there. (Note: the
user-facing `page_state` include/exclude flags in `bundle.json` are *curation
choices*, not the primary/context distinction — don't conflate the two.)

## How to walk an export programmatically

A reliable traversal that doesn't depend on guessing filenames:

1. Read `bundle.json`; verify `version == 1`.
2. Compute the effective page set from `selected_items` + `page_state` (formula
   above) — or, equivalently, just enumerate the `<root_id>/` folders and the
   `*.txt` / image files in them.
3. For each volume folder, read `volume.json` for `label`/`title` and the
   ordered `pages[]`.
4. For each bundled `page_key`, open `<page_key>.txt` for text (it may be HTML),
   `<page_key>.json` for the source annotations, `<page_key>.names.json` for
   the extracted people, `<page_key>.notes.md` for the user's corrections
   (apply them over the names — see above), and `<page_key>` for the image if
   it exists. Any of the five may be absent — check before opening.
5. Order pages within a volume by their index in `volume.json` `pages[]`.

## Quick reference

| File | Always present? | Source / meaning |
|---|---|---|
| `bundle.json` | Yes | Selection manifest; `version`, `created_at`, `selected_items`, `page_state`. |
| `<root_id>/volume.json` | Yes (may be `{}`) | Volume `label`, `reference_code`, `title`, full ordered `pages[]`. |
| `<root_id>/<page_key>.txt` | Only if page has a transcription | Flattened page transcription; **may contain HTML**; page-level, not per-resource. |
| `<root_id>/<page_key>.json` | Only if page has annotations | Raw IIIF `sc:AnnotationList` the `.txt` came from. |
| `<root_id>/<page_key>.names.json` | Only if `vtextract names` ran on the page | Extracted people; `people[]` of `[canonical, *surface_forms]` arrays (schema 2). |
| `<root_id>/<page_key>.notes.md` | Only if the user wrote notes for the page | Human-authored Markdown; **overrides** `.names.json` and corrects the `.txt`; may postdate the names pass. |
| `<root_id>/<page_key>` | Only if exported with images | The page image (JPEG); filename **is** the `page_key`. |
