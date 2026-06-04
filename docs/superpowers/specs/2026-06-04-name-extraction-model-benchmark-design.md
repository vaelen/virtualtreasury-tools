# Name-extraction model benchmark (`vtnamebench`) — design

**Date:** 2026-06-04
**Status:** Approved

## Purpose

A small standalone tool to compare how several LLMs perform on the
person-name-extraction task — using the **exact same prompt and setup as
`vtextract names`** — over a folder of plain `.txt` files. It produces per-model
`.names.json` sidecars and per-file timings, then prints a summary report
comparing the number of high/medium/low quality names extracted and the average
time per file.

## Scope

In scope: a new `vtnamebench` console entry point, per-model output + timing
files, resumable skipping, and a console summary report. Out of scope: changing
the real `vtextract names` pipeline, accuracy/ground-truth scoring, image
handling.

## Architecture & placement

- New module `src/vtextract/namebench.py` exposing `main()`, registered in
  `pyproject.toml` as `vtnamebench = "vtextract.namebench:main"`.
- Invocation: `uv run vtnamebench path/to/bench.toml [--force]`.
- **Reuses the real `names` pipeline** — imports `chunk_text`
  (`vtextract.names.chunking`), `find_people` (`vtextract.names.llm`, the exact
  `SYSTEM_PROMPT` + retry/backoff), and `merge_people`
  (`vtextract.names.merge`). The per-file extraction replicates the small
  chunk→find→merge loop from `extractor._extract_one` (the only file-path-specific
  part), keeping prompt + chunking identical. A single injectable `find` seam
  (defaulting to `llm.find_people`) makes the extraction offline-testable, the
  same pattern `extractor.extract` uses.
- `chunk_size` / `overlap` come from the user's `[names]` config defaults
  (`load_config()` → `NamesConfig`, i.e. 64000 / 512). By default `api_base` is
  `None` so LiteLLM routes by the `provider/` prefix (cloud models span
  Anthropic + OpenAI, so a single global `api_base` would not fit). Models that
  need a custom endpoint (e.g. a local `ollama/...` server) get a **per-model**
  `api_base` from the bench config's optional `[api_base]` table (see below);
  models absent from that table keep provider routing.

## Config & I/O layout

Bench config is TOML:

```toml
input = "~/foo/bar"
models = [
  "anthropic/claude-haiku-4-5",
  "anthropic/claude-sonnet-4-6",
  "openai/gpt-4.1-mini",
  "openai/gpt-4.1",
  "ollama/llama3",
]

# Optional: custom endpoint per model. Models absent here use provider routing.
[api_base]
"ollama/llama3" = "http://localhost:11434"
```

- `input` is expanded (`~`) and resolved; it is the folder of `.txt` files.
- `[api_base]` is an optional table mapping a model string (exactly as it
  appears in `models`) to an endpoint URL. Defaults to empty. A model's
  `api_base` is `bench.api_base.get(model)` (i.e. `None` when unlisted), passed
  to `run_model`/`extract_people` and on to the `find` seam — the same
  `api_base` `vtextract names` threads to LiteLLM. Must parse as a table of
  string→string; anything else is a config error.
- For each model, output goes to `<input>/models/<model>/`. The model string is
  used verbatim as a relative path, so `anthropic/claude-haiku-4-5` nests two
  levels (matches the example layout).
- Per file `N.txt` → `N.txt.names.json` (keeps the `.txt`, per the example),
  written atomically (tmp + `os.replace`). Sidecar shape is identical to
  `vtextract names`: `{"schema": SIDECAR_SCHEMA, "model": <model>, "people":
  [...]}`.
- `times.json` lives in each model dir and maps `{"N.txt": <seconds:float>}`.
  Loaded at start; only files processed this run are added/updated; existing
  entries for skipped files are preserved. Rewritten atomically after each file
  so a crash mid-run keeps completed timings.

Example tree:

```
~/foo/bar
  1.txt
  2.txt
  models/
    anthropic/
      claude-haiku-4-5/
        times.json
        1.txt.names.json
        2.txt.names.json
```

**Skip rule:** a file is "already processed by that model" iff its
`.names.json` sidecar exists. `--force` re-runs everything (refreshing timings).

## Processing & timing

- Outer loop over `models`, inner loop over `sorted(<input>/*.txt)`, **sequential**
  (chunks within a file already run sequentially in the reused loop). Sequential
  processing gives clean per-file timing and avoids shared-credential rate-limit
  contention.
- **Model lifecycle (production path only).** Before processing a model that has
  work, the CLI evicts the previously-loaded local (Ollama) model via
  `llm.unload` (a `keep_alive=0` request, a no-op for non-Ollama) to ease GPU
  pressure, then preflights/warms the current model via `llm.check_model` (a
  tiny request that loads it). This keeps a local model's **cold-start load cost
  out of the first file's timing** and surfaces auth/config errors before
  churning every file. A preflight error skips that model (its files retry next
  run). The last local model is evicted when the run ends. Lifecycle management
  is gated on the real provider being used (the CLI's `find` is `None`); an
  injected `find` (tests) loads/evicts nothing.
- Per unprocessed file: `t = perf_counter()`, run chunk→find→merge,
  `dt = perf_counter() - t`, write sidecar, set `times[name] = dt`, rewrite
  `times.json`.
- On failure (exhausted retries / malformed JSON), mirror `vtextract names`:
  log one `llm.friendly_error(...)` line to stderr, write **no** sidecar and
  **no** time entry, continue — so the file retries on a later run.

## Summary report (console only)

Built by **re-scanning disk**, not just this run's results, so it covers models
that were fully skipped this run and models from prior runs:

- For every model directory under `<input>/models/` that contains ≥1 sidecar,
  aggregate across its sidecars.
- **Quality count:** every name — each person's `canonical` **and** each alias —
  is counted once, bucketed by *its own* `confidence` into high/medium/low.
- **Timing distribution:** from that model's `times.json` values — `min`, `max`,
  `median`, and `mean` seconds. Median is reported alongside mean because a few
  long transcriptions skew the mean upward.
- **Length-normalized throughput (`ms/byte`):** total recorded seconds across
  the model's timed files divided by the total byte size of those input files,
  in milliseconds per byte. This makes models comparable independent of how long
  each document happens to be (the dominant source of per-file timing variance).
- Rendered as a Rich table (fixed wide width so model names never truncate when
  piped), one row per model:

  | Model | Files | High | Med | Low | Total | Min s | Max s | Median s | Mean s | ms/byte |

- Models with no on-disk data are omitted. Timing columns are `n/a` when no
  `times.json` entries exist.

Model directories are discovered by walking `<input>/models/` for directories
containing a `times.json` or any `*.names.json`, reconstructing the model string
from the path relative to `models/`.

## Error handling

- Missing/invalid bench config, missing `input` dir, empty `models` → clear
  error to stderr, non-zero exit.
- Per-file extraction failures are logged and skipped (see Processing & timing);
  one bad file does not abort the model or the run.

## Testing

Pytest against `tmp_path`, **no network** (repo rule). Inject a stub `find`
returning canned `Person` lists. Cover:

- sidecars + `times.json` written to the correct per-model paths;
- existing sidecar ⇒ file skipped (and its prior time preserved);
- `--force` re-processes;
- a failing `find` for one file ⇒ logged, no sidecar/time, other files proceed;
- report aggregation buckets persons + aliases by their own confidence, and
  includes a model that has on-disk data but was not run this session;
- TOML config parsing (input expansion, models list).
```
