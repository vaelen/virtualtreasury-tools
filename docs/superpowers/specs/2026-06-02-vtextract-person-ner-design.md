# vtextract person-NER enrichment — Design

**Date:** 2026-06-02
**Status:** Draft (pending spec review)

## Purpose

Build a searchable index of which archived documents mention a **specific
person**, using an LLM to perform named-entity recognition over the archive's
transcriptions. A regex cannot distinguish the person "Young" from the adjective
"young", collapse `Wm Young` / `Sgt. Young` / `Thomas Young` into one individual,
or reject an unrelated person who merely shares a surname. An LLM can.

LLM calls are expensive (money for a remote model, time for a local one), so the
expensive work is done **once per physical page** and persisted as durable
on-disk **source data** (sidecar files). A cheap, freely-rebuildable index is
then derived from those sidecars — exactly the durable-source / disposable-index
split the existing `vtindex` already follows.

This embeds the functionality of the standalone `name-grep` tool
(`~/repos/name-grep`) into this repo; it does **not** depend on or shell out to
that project. The relevant pieces (the person-NER LiteLLM wrapper, prompt,
chunking) are ported into a new `entities/` subpackage.

## Why "extract all people once" beats "search one name at a time"

`name-grep` answers a *targeted* question — "does **this** person appear in this
text?" — so every new name is another full LLM pass over the whole archive:
O(pages × names) LLM calls.

Extracting **all** people from each page once, then indexing the results, makes
the expensive work **query-independent**: O(pages) LLM calls, after which any
person can be found with zero further LLM calls. The extraction output becomes
the precious artifact; the index built from it is as cheap to rebuild as the
existing FTS index.

## Scope

In scope (v1):
- A new `vtextract names` subcommand: an expensive, resumable, whole-archive
  pass that writes one person-NER sidecar per page transcription.
- Per-page extraction of **people only** (no places/orgs/relationships).
- **Within-page canonicalization**: expand common abbreviations to full names
  (`Wm`→`William`, `Thos`→`Thomas`, `Jno`→`John`, `Geo`→`George`, …) and collapse
  surface forms the model is confident refer to the same person on that page
  (e.g. `Thomas Young` + `Sgt. Young` → one entry) into a canonical name plus a
  list of aliases, each with its own confidence.
- Ingest of sidecars into **new person tables in the existing `vtindex` DB**, and
  a `vtindex people "<name>"` query.

Out of scope (YAGNI for v1):
- Places, organizations, relationships, or dates.
- **Cross-page** coreference (linking the same person across different pages).
  Canonicalization narrows this gap for free (see below) but does not close it.
- Per-alias context snippets in the sidecar (kept lean: alias text + confidence).
- TUI (`vtbrowse`) integration — a follow-up, not v1.
- `--images`-style integration into the per-resource fetch flow; extraction is a
  separate whole-archive pass.

## Domain fit (per-page, like everything else here)

Transcriptions are **page-level, not resource-level** (one physical page can
carry several resources). Pages are therefore stored once at
`archive/pages/{rootID}/{page_key}.txt`. Person extraction follows the same
grain: it runs once per page transcription and writes one sidecar per page, so a
page shared by three resources is extracted **once**. The index maps
person → page, and the existing page → item relationship composes person → item
for free.

Because extraction is per-page, coreference collapsing is **within a page only**.
The model can merge `Thomas Young` and `Sgt. Young` when they appear on the same
page; it cannot merge mentions split across pages. Canonicalization partly
bridges this: if page A writes "William Young" and page B writes "Wm Young", both
canonicalize to `William Young`, so a search for either form finds both pages
even though no cross-page linking occurred.

## Architecture

### New subpackage: `src/vtextract/entities/`

The single boundary for LLM calls — analogous to `client.py` being the single
VTRI-HTTP choke point. Nothing else in the codebase calls an LLM.

| Module | Responsibility |
|---|---|
| `llm.py` | Ported LiteLLM wrapper: the person-NER + canonicalization system prompt, lenient JSON parse, one reprompt on bad JSON, backoff retry on transport errors, `friendly_error`, `check_model` preflight. The **sole** LLM caller. |
| `chunking.py` | Ported overlapping-window splitter. Page transcriptions are small (usually one chunk) but chunking is kept for safety; per-chunk results are merged before canonicalization is finalized. |
| `extractor.py` | Orchestrate: enumerate `archive/pages/**/*.txt`, skip pages that already have a `.entities.json` (resume), `ThreadPoolExecutor` over the rest, write each sidecar atomically, emit progress via the existing `progress` module. |
| `models.py` | `Person`, `Alias`, `Sidecar` dataclasses / Pydantic models for validation. |

### CLI

`vtextract names [refcodes/ids…] [--archive PATH] [--force] [--model M] [-w N] [--config PATH]`

- No positional args → the whole archive (all page transcriptions).
- Positional refcodes/ids → scope a partial run to those resources' pages.
- `--force` → re-extract and overwrite existing sidecars (e.g. after a model
  upgrade); default skips pages that already have a sidecar.
- Test seam consistent with the rest of the CLI: the LLM call function is
  injectable so tests never hit a live model.

### Config

A new `[entities]` section in `~/.vt/vt.toml` (same config file as the rest of
vtextract — no new env vars, no second config):

```toml
[entities]
model = "ollama/llama3.1"
# api_base = "http://localhost:11434"
chunk_size = 64000
workers = 1
# confidence = "low"   # default display floor for `vtindex people` (query-time only)
```

### Sidecar (the precious, durable source data)

Path: `archive/pages/{rootID}/{page_key}.entities.json`, adjacent to the
existing `{page_key}.txt` (transcription) and `{page_key}.json` (annotations).

```json
{
  "schema": 1,
  "model": "ollama/llama3.1",
  "people": [
    {
      "canonical": "William Young",
      "confidence": "high",
      "aliases": [
        {"text": "Wm Young",  "confidence": "high"},
        {"text": "Sgt. Young", "confidence": "medium"},
        {"text": "Young",      "confidence": "low"}
      ]
    }
  ]
}
```

- `schema` and `model` are recorded so a later run can detect stale or
  under-powered extractions and `--force`-refresh them.
- Entry-level `confidence` = the model's confidence in the canonical identity /
  expansion. Per-alias `confidence` = confidence that *that surface form* refers
  to this person (the signal used to keep or drop a shaky merge at query time).
- Initials (`J. Young`) are never used to drive an expansion; they attach only as
  a low-confidence alias when context supports it, else remain their own entry.
- **Nothing is filtered out at extraction time** — the sidecar keeps everything,
  including low-confidence entries. Filtering happens only at query time. A wrong
  coreference merge therefore stays inspectable and reversible in the file.
- `"people": []` is a real result (page mentions no people) and counts as "done"
  so resume skips it.

### Index ingest + query (existing `vtindex` DB, new tables)

- `index/reader.py` — add `read_entities(sidecar_path) -> Sidecar` (pure parse),
  parallel to `read_transcription`.
- `index/db.py` — new tables (the single SQL choke point):
  - `person(id, canonical, page_root_id, page_key, confidence)`
  - `person_alias(person_id, text, confidence)`
  - FTS5 over `canonical` + alias `text`, so any surface form matches and results
    display the canonical name.
- `index/builder.py` — same stat-fingerprint incremental build as today; a
  changed or new sidecar re-ingests just that page's people.
- `index/query.py` + `index/cli.py` — `vtindex people "<name>" [--confidence LEVEL] [--json]`
  → matching people with their pages and the items those pages belong to. FTS over
  names gives token matching ("Young" finds every Young); `--confidence` filters
  at query time.

### Boundaries preserved

- `entities/llm.py` is the only LLM caller (new external-call choke point).
- `vtindex` stays a pure archive-reader → derived-DB tool: it **reads** sidecars,
  never writes archive source data. Writing sidecars belongs to `vtextract`
  (like `fetcher` writing transcriptions).
- `tui/` touches none of this directly (the existing CI boundary test still
  holds).

## Data flow

1. `vtextract names` → config (`[entities]`) + page-transcription file list.
2. Per page: read `.txt` → chunk → `entities.llm` per chunk → merge chunk
   results → canonicalize/collapse within the page → write `.entities.json`.
   Skip if a sidecar already exists (unless `--force`).
3. `vtindex build` → for each new/changed sidecar, `read_entities` → upsert
   `person` / `person_alias` rows + FTS.
4. `vtindex people "<name>"` → FTS match over canonical + aliases → people →
   pages → items, filtered by `--confidence`.

## The LLM contract

Ported and extended from name-grep's person-NER prompt. The model is instructed
to, for one block of text:

- Find every distinct **person** (reject ordinary words that resemble a name and
  unrelated people who merely share a surname/first name).
- Produce a **canonical** full name per person, expanding common abbreviations
  (`Wm`→`William`, `Thos`→`Thomas`, `Jno`→`John`, `Geo`→`George`, titles dropped
  from the canonical) — but **never** expand a bare initial into a guessed first
  name.
- **Collapse** surface forms it is confident refer to the same person in this
  text into one entry, listing each surface form under `aliases` with a
  per-alias confidence; keep uncertain forms as separate entries rather than
  over-merging.
- Return JSON only:
  ```json
  {"people": [
    {"canonical": "...", "confidence": "low|medium|high",
     "aliases": [{"text": "...", "confidence": "low|medium|high"}]}
  ]}
  ```
- An empty `people` array means no genuine person mentions.

Validated with a Pydantic model; malformed output is reprompted once, then the
chunk is skipped with a stderr warning. Transport errors retry with backoff.

## Error handling

- Reuse name-grep's `friendly_error` / `check_model` preflight so an unreachable,
  missing, or unauthorized model fails fast with one clear message rather than
  once per page.
- A page whose extraction fails (after retries/reprompt) is left **without** a
  sidecar so a later run retries it — failure must not be recorded as "done".
- Sidecars are written atomically (temp file + rename) so an interrupted run
  never leaves a half-written sidecar that resume would treat as complete.

## Testing

- **TDD** throughout; every feature commit pairs code with its test.
- LLM is **mocked** (inject the completion/find function), exactly as name-grep
  mocks it and as vtextract mocks HTTP via `MockTransport`. **No live LLM and no
  network in the suite** — consistent with the fixture-only tests today.
- New fixtures: a couple of `.entities.json` sidecars under a fixture archive for
  the reader/builder/query tests; canned LLM responses for the extractor tests.
- Tests pass a `--config` path to a `tmp_path` file; the credential / model
  config is never hardcoded.
- Boundary test: `vtindex` does not write archive source files; `tui/` does not
  import the new modules.

## Follow-ups (not v1)

- `vtbrowse` integration: a person-search pane / filter over the index.
- Cross-page coreference (global identity resolution across the archive).
- Optional per-alias context snippets for richer in-file auditing.
- Places / organizations extraction (the schema and command generalize, but are
  deliberately out of v1 scope).
