# Durable failure records for `vtextract names`

Date: 2026-06-06

## Problem

`vtextract names` decides what to process purely on `sidecar.exists()`
(`extractor.py:180-184`). When a page's extraction fails — including a
truncation / repetition-loop failure that survives the hotter retry — **no
sidecar is written**: the run logs to stderr and bumps `stats.failed`
(`extractor.py:206-208`). On disk such a page is indistinguishable from one
that was never touched.

Two consequences:

1. **Re-burn.** Every subsequent run re-attempts persistently-failing pages
   from scratch, spending tokens and wall-clock on pages that will deterministic­ally
   fail again, and never converging.
2. **Invisibility.** There is no durable record of *which* pages failed or
   *why*, so a large run's failures are only knowable by scraping stderr.

## Goals

- Record persistent, page-deterministic failures durably so a normal re-run
  **skips** them instead of re-attempting from scratch, with an explicit
  `--retry-failed` (and `--force`) to re-attempt.
- Make those failures visible/queryable: a durable on-disk record plus a
  `--list-failed` view.

## Non-goals (YAGNI)

- No time-based auto-expiry of parked pages.
- No `vtindex` / TUI ingestion of failures (the error sidecars stay a
  names-tool concern).
- No new in-run recovery strategy (e.g. chunk-shrinking). The existing hot-retry
  stays; persistent failures are simply parked rather than retried blindly.

## Key distinction: persistent vs transient failures

Only **page-content-deterministic** failures get a durable, skip-causing
record. These are the failures that will recur identically on the same input:

- `TruncatedResponseError` (output-token cap / repetition loop) → `error_class`
  **`"truncated"`**.
- `JSONDecodeError` / `ValidationError` (model did not return valid JSON, even
  after the retry) → `error_class` **`"bad_json"`**.

Everything else is **transient** (environmental, not page-specific) and keeps
today's behavior — logged, no sidecar, retried next run:

- rate-limit, auth, model-not-found, connection, and any unclassified error.

Auth and not-found are deliberately *transient* here: they fail on *every* page
of a misconfigured run, so recording a per-page error sidecar for them would
spam the archive; fixing config + re-running is the correct recovery.

## Design

### 1. On-disk format — the error sidecar

A sibling file `{page_key}.names.error.json` in `archive/pages/{rootID}/`,
written atomically with the same temp-then-`os.replace` pattern as the success
sidecar (`_write_sidecar_atomic`).

```json
{
  "schema": 1,
  "model": "gemini/gemini-2.5-flash-lite",
  "error_class": "truncated",
  "finish_reason": "length",
  "attempts": 3,
  "last_attempt": "2026-06-06T14:02:11Z",
  "message": "Model '...' hit its output-token limit and the response was cut off mid-JSON ..."
}
```

- `error_class` ∈ `{"truncated", "bad_json"}`.
- `finish_reason`: the provider's value for a truncation (e.g. `"length"`),
  else `null` (bad_json).
- `attempts`: read-modify-write — incremented each time a persistent failure is
  re-recorded for the page (prior count read from any existing error sidecar;
  starts at 1). Per-file, so safe under `--workers`.
- `last_attempt`: ISO-8601 UTC timestamp.
- `message`: the full `friendly_error()` text (durable + actionable; truncated
  only for table display in `--list-failed`).
- New constant `ERROR_SIDECAR_SCHEMA = 1` in `models.py`.

**Invariant:** a present *success* sidecar always means the page is done. A
successful extraction **removes** any stale error sidecar for that page; a
normal skip-as-done also opportunistically removes an error sidecar if both
somehow coexist (success wins).

### 2. Failure classifier — a new seam in `llm.py`

The failure type is an LLM-domain fact, so the classifier lives at the LLM
boundary (`names/llm.py`) as two pure functions:

```python
def error_class(exc: Exception) -> str | None:
    """ "truncated" | "bad_json" | None (== transient). """

def is_persistent_failure(exc: Exception) -> bool:
    return error_class(exc) is not None
```

They walk the `__cause__` chain, because `_extract_one` re-raises the real
error wrapped in `RuntimeError("chunk N/M failed ...") from exc`
(`extractor.py:138-141`):

- `isinstance(cur, TruncatedResponseError)` → `"truncated"`
- `isinstance(cur, (json.JSONDecodeError, ValidationError))` → `"bad_json"`
- fallback: `_TRUNCATION_MARKER in str(exc)` → `"truncated"`
- otherwise → `None`

`TruncatedResponseError` gains a `finish_reason` attribute (set at raise sites,
`llm.py:377-379` and the retry path) so the error sidecar can record
`finish_reason` without string-parsing the message.

### 3. `extract()` resume + write logic

New parameter `retry_failed: bool = False`. Page selection:

| On-disk state                       | Normal run        | `retry_failed`  | `force`  |
| ----------------------------------- | ----------------- | --------------- | -------- |
| success sidecar present             | skip (`skipped`)  | skip            | re-do    |
| error sidecar present, no success   | skip (`parked`)   | re-attempt      | re-do    |
| neither                             | process           | process         | process  |

Per-page result handling in `run()`:

- **Success** → write success sidecar; delete any error sidecar; `extracted += 1`.
- **Persistent failure** (`error_class(exc) is not None`) → write/increment the
  error sidecar; `failed_persistent += 1`; still log to stderr via
  `_log_failure`.
- **Transient failure** → unchanged: log, no sidecar; `failed += 1`.

`force` implies retry (it reprocesses everything and the success path clears the
error sidecar). The `attempts` read-modify-write happens at write time inside
the new `_write_error_sidecar` helper, so no extra state is threaded through the
worker.

### 4. `NamesStats`, CLI, and summary

`NamesStats` gains:

- `parked: int` — pages skipped this run because a persistent-error sidecar
  exists (and we are not retrying).
- `failed_persistent: int` — pages that failed persistently this run and got an
  error sidecar written/updated.
- `failed` now counts **transient-only** failures.

The `names` command gains two flags:

- `--retry-failed` — re-attempt parked pages (composes with identifier scoping
  and `scope_pages`). Passed through to `extract(retry_failed=...)`.
- `--list-failed` — no extraction. Walk error sidecars (scoped by `identifiers`
  if given) via a new **pure** helper in `extractor.py`,
  `iter_error_sidecars(archive, scope_pages=None) -> list[ErrorRecord]`, and
  print a Rich table (page, class, attempts, when, message). Returns 0.
  Short-circuits in `_run_names` *before* model/config-model resolution (no LLM,
  no model needed).

The end-of-run summary distinguishes the buckets, e.g.:

```
names: 120 extracted, 540 skipped, 2 parked, 1 new persistent error,
0 transient failures (3400 people). Re-run parked pages with --retry-failed.
Run `vtindex build --archive <archive>` to index them.
```

The `--retry-failed` hint is shown only when `parked + failed_persistent > 0`.

`cli.py` stays thin (table rendering + flag wiring); the walking/format logic
lives in `extractor.py`.

### 5. Compatibility

- Verify `vtindex` ingestion (`index/reader.py` / `builder.py`) globs
  `*.names.json` and therefore does **not** pick up `*.names.error.json`
  (different suffix). Add a guard test pinning this.
- `page_transcriptions` globs `*/*.jpg.txt`; the error sidecar
  (`*.jpg.names.error.json`) does not match.

## Testing (TDD, fixtures only, no network)

- **Classifier** (`error_class` / `is_persistent_failure`): truncated, bad_json,
  the same wrapped in `RuntimeError(...) from exc`, and transient cases
  (rate-limit, auth, connection, unknown) → `None`.
- **Write-on-persistent-fail**: a persistent failure writes an error sidecar
  with `attempts == 1` and the right `error_class` / `finish_reason`; a
  transient failure writes **no** sidecar (today's behavior preserved).
- **Resume**: error sidecar present ⇒ page skipped (`parked`) on a normal run;
  `retry_failed=True` ⇒ page re-attempted; `force=True` ⇒ re-attempted.
- **Cleanup**: a success after a prior error removes the error sidecar; a
  skip-as-done with both present removes the error sidecar.
- **attempts** increments across successive persistent failures.
- **`iter_error_sidecars`**: returns the expected records; honours identifier
  scoping.
- **CLI smoke**: `--retry-failed` reaches `extract(retry_failed=True)`;
  `--list-failed` prints rows and returns 0 without touching the LLM seam.
- **Compat guard**: an archive containing a `*.names.error.json` builds in
  `vtindex` without ingesting it as people.

## Files touched

- `src/vtextract/names/models.py` — `ERROR_SIDECAR_SCHEMA`; `NamesStats` fields.
- `src/vtextract/names/llm.py` — `error_class`, `is_persistent_failure`;
  `TruncatedResponseError.finish_reason`.
- `src/vtextract/names/extractor.py` — error-sidecar write/cleanup,
  `retry_failed` selection, `iter_error_sidecars`, summary stats.
- `src/vtextract/cli.py` — `--retry-failed`, `--list-failed`, summary text,
  help/epilog.
- `README.md` — document the new flags and the parked-failure workflow.
- Tests alongside each (`tests/...`).
