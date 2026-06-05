# Durable Failure Records for `vtextract names` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record page-deterministic `names` extraction failures (truncation / bad-JSON) as durable sibling sidecars so normal re-runs skip them instead of re-burning tokens, and make them inspectable via `--list-failed` / `--retry-failed`.

**Architecture:** A new failure classifier at the LLM boundary (`names/llm.py`) splits exceptions into *persistent* (truncated / bad_json) vs *transient*. The extractor writes a `{page_key}.names.error.json` sidecar only for persistent failures, removes it on a later success, and skips parked pages unless `--retry-failed`/`--force`. The CLI gains `--retry-failed` and a no-extraction `--list-failed` view.

**Tech Stack:** Python 3, `uv`/`pytest`, `pydantic`, `rich`, `litellm` (already in use). Tests run against `tmp_path` fixtures, never the network.

**Reference spec:** `docs/superpowers/specs/2026-06-06-names-failure-records-design.md`

---

## File Structure

- `src/vtextract/names/models.py` — add `ERROR_SIDECAR_SCHEMA` constant; extend `NamesStats` with `parked` and `failed_persistent`.
- `src/vtextract/names/llm.py` — add `finish_reason` attribute to `TruncatedResponseError`; add pure classifiers `error_class`, `is_persistent_failure`, `truncation_finish_reason`.
- `src/vtextract/names/extractor.py` — error-sidecar path/write/cleanup helpers, `retry_failed` selection, persistent-vs-transient result handling, `iter_error_sidecars` + `ErrorRecord` for listing.
- `src/vtextract/cli.py` — `--retry-failed` and `--list-failed` flags, updated summary line, updated exit code, updated description/epilog.
- `README.md` — document the new flags and parked-failure workflow.
- Tests: `tests/names/test_llm.py`, `tests/names/test_extractor.py`, `tests/test_cli_names.py`, and a new `tests/names/test_error_sidecar_index_compat.py`.

Conventions (from CLAUDE.md): TDD (failing test first), conventional commits, fixtures only. Run tests with `uv run pytest`.

---

## Task 1: `NamesStats` fields + error-sidecar schema constant

**Files:**
- Modify: `src/vtextract/names/models.py` (the `NamesStats` dataclass ~`models.py:46-51`, and the `SIDECAR_SCHEMA` constant ~`models.py:15`)
- Test: `tests/names/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/names/test_models.py`:

```python
def test_names_stats_has_failure_buckets():
    from vtextract.names.models import NamesStats
    s = NamesStats()
    assert s.parked == 0
    assert s.failed_persistent == 0


def test_error_sidecar_schema_constant_present():
    from vtextract.names.models import ERROR_SIDECAR_SCHEMA
    assert ERROR_SIDECAR_SCHEMA == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/names/test_models.py -k "failure_buckets or error_sidecar_schema" -v`
Expected: FAIL — `AttributeError: ... 'parked'` / `ImportError: cannot import name 'ERROR_SIDECAR_SCHEMA'`.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/names/models.py`, just below the existing `SIDECAR_SCHEMA = 1` line add:

```python
# On-disk error-sidecar format version. Bump if the error JSON shape changes.
ERROR_SIDECAR_SCHEMA = 1
```

Extend the `NamesStats` dataclass (keep existing fields and comments):

```python
@dataclass
class NamesStats:
    extracted: int = 0          # pages a fresh sidecar was written for
    skipped: int = 0            # pages skipped (success sidecar already present)
    parked: int = 0             # pages skipped (persistent-error sidecar present)
    failed: int = 0             # transient failures this run (no sidecar written)
    failed_persistent: int = 0  # persistent failures this run (error sidecar written)
    people: int = 0             # total Person entries written across all sidecars
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/names/test_models.py -v`
Expected: PASS (all tests in file).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/models.py tests/names/test_models.py
git commit -m "feat: add parked/persistent failure buckets and error-sidecar schema to names models"
```

---

## Task 2: Failure classifier at the LLM boundary

**Files:**
- Modify: `src/vtextract/names/llm.py` (`TruncatedResponseError` ~`llm.py:76-86`; both raise sites ~`llm.py:377-379`; add new functions near `friendly_error`)
- Test: `tests/names/test_llm.py`

Context: `_extract_one` re-raises the real error wrapped as `RuntimeError("chunk N/M failed ...: <exc>") from exc`, so classifiers MUST walk the `__cause__` chain. `json` and `ValidationError` are already imported in `llm.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/names/test_llm.py`:

```python
import json as _json
from pydantic import ValidationError

from vtextract.names.llm import (
    TruncatedResponseError,
    error_class,
    is_persistent_failure,
    truncation_finish_reason,
)
from vtextract.names.models import NameResponse


def _wrap(cause: Exception) -> Exception:
    # Mirror extractor._extract_one: RuntimeError(...) from cause.
    try:
        raise cause
    except Exception as inner:
        try:
            raise RuntimeError(f"chunk 1/1 failed for x: {inner}") from inner
        except RuntimeError as wrapped:
            return wrapped


def test_error_class_truncated_direct_and_wrapped():
    exc = TruncatedResponseError(
        "response truncated at output-token limit (finish_reason=length)",
        finish_reason="length")
    assert error_class(exc) == "truncated"
    assert error_class(_wrap(exc)) == "truncated"
    assert is_persistent_failure(_wrap(exc)) is True


def test_error_class_bad_json_direct_and_wrapped():
    jexc = _json.JSONDecodeError("Expecting value", "", 0)
    assert error_class(jexc) == "bad_json"
    assert error_class(_wrap(jexc)) == "bad_json"
    try:
        NameResponse.model_validate({"people": "not-a-list"})
        raise AssertionError("expected ValidationError")
    except ValidationError as vexc:
        assert error_class(vexc) == "bad_json"
        assert error_class(_wrap(vexc)) == "bad_json"


def test_error_class_transient_returns_none():
    assert error_class(ConnectionError("connection refused")) is None
    assert error_class(RuntimeError("rate limit: 429 too many requests")) is None
    assert is_persistent_failure(ConnectionError("nope")) is False


def test_truncation_finish_reason_walks_chain():
    exc = TruncatedResponseError("response truncated ...", finish_reason="max_tokens")
    assert truncation_finish_reason(exc) == "max_tokens"
    assert truncation_finish_reason(_wrap(exc)) == "max_tokens"
    assert truncation_finish_reason(ConnectionError("x")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/names/test_llm.py -k "error_class or persistent or finish_reason" -v`
Expected: FAIL — `ImportError`/`TypeError: __init__() got an unexpected keyword argument 'finish_reason'`.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/names/llm.py`, replace the `TruncatedResponseError.__init__` to accept `finish_reason`:

```python
    def __init__(self, message: str, usage: "Usage | None" = None,
                 finish_reason: str | None = None) -> None:
        super().__init__(message)
        self.usage = usage
        self.finish_reason = finish_reason
```

Update the raise site in `_complete` (~`llm.py:377-379`) to pass it:

```python
                raise TruncatedResponseError(
                    f"{_TRUNCATION_MARKER} (finish_reason={_finish_reason(choice)})",
                    usage=usage, finish_reason=_finish_reason(choice))
```

Add the classifiers immediately after `friendly_error` (after ~`llm.py:214`):

```python
def error_class(exc: Exception) -> str | None:
    """Persistent (page-deterministic) failure class, else None (transient).

    Walks the ``__cause__`` chain because the extractor re-raises the real cause
    wrapped in a RuntimeError. Only truncation and malformed-JSON are persistent
    -- they recur identically on the same input. Rate-limit, auth, not-found and
    connection errors are environmental, so they return None and keep retrying.
    """
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, TruncatedResponseError):
            return "truncated"
        if isinstance(cur, (json.JSONDecodeError, ValidationError)):
            return "bad_json"
        cur = cur.__cause__
    if _TRUNCATION_MARKER in str(exc):
        return "truncated"
    return None


def is_persistent_failure(exc: Exception) -> bool:
    """True when the failure is page-deterministic (worth parking on disk)."""
    return error_class(exc) is not None


def truncation_finish_reason(exc: Exception) -> str | None:
    """The provider finish_reason carried by a TruncatedResponseError, if any."""
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, TruncatedResponseError):
            return cur.finish_reason
        cur = cur.__cause__
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/names/test_llm.py -v`
Expected: PASS (whole file — confirms no regression in existing llm tests).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/llm.py tests/names/test_llm.py
git commit -m "feat: classify names LLM failures as persistent vs transient"
```

---

## Task 3: Error-sidecar path + atomic write helper

**Files:**
- Modify: `src/vtextract/names/extractor.py` (add suffix constant near `extractor.py:33-34`, add helpers near `sidecar_for`/`_write_sidecar_atomic` ~`extractor.py:78-98`; add imports)
- Test: `tests/names/test_extractor.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/names/test_extractor.py`:

```python
def test_error_sidecar_for_replaces_suffix(tmp_path):
    from vtextract.names.extractor import error_sidecar_for
    txt = tmp_path / "x.jpg.txt"
    assert error_sidecar_for(txt).name == "x.jpg.names.error.json"


def test_write_error_sidecar_increments_attempts(tmp_path):
    from vtextract.names.extractor import error_sidecar_for, _write_error_sidecar
    txt = tmp_path / "x.jpg.txt"
    txt.write_text("body")
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="cut off")
    data = json.loads(error_sidecar_for(txt).read_text())
    assert data["schema"] == 1
    assert data["model"] == "m"
    assert data["error_class"] == "truncated"
    assert data["finish_reason"] == "length"
    assert data["attempts"] == 1
    assert data["message"] == "cut off"
    assert data["last_attempt"].endswith("Z")
    # second write for the same page bumps the counter
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="cut off again")
    data2 = json.loads(error_sidecar_for(txt).read_text())
    assert data2["attempts"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/names/test_extractor.py -k "error_sidecar_for or write_error_sidecar" -v`
Expected: FAIL — `ImportError: cannot import name 'error_sidecar_for'`.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/names/extractor.py`, extend the imports at the top:

```python
from datetime import datetime, timezone
```

and the models import to include the new schema constant:

```python
from vtextract.names.models import (
    ERROR_SIDECAR_SCHEMA,
    SIDECAR_SCHEMA,
    NamesStats,
    Person,
    Usage,
    people_and_usage,
    sum_usage,
)
```

Add the suffix constant next to the existing ones (~`extractor.py:33-34`):

```python
_ERROR_SUFFIX = ".names.error.json"
```

Add these helpers right after `_write_sidecar_atomic` (~`extractor.py:98`):

```python
def error_sidecar_for(txt_path: Path) -> Path:
    """Map <page_key>.txt -> <page_key>.names.error.json (same directory)."""
    txt_path = Path(txt_path)
    return txt_path.with_name(txt_path.name[: -len(_TXT_SUFFIX)] + _ERROR_SUFFIX)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_error_sidecar(txt_path: Path, *, model: str, error_class: str,
                         finish_reason: str | None, message: str) -> None:
    """Write/refresh the persistent-failure sidecar for a page.

    Read-modify-write of ``attempts`` (prior count + 1). Per-page file, so this
    is safe under --workers. Atomic via temp-then-os.replace, like the success
    sidecar.
    """
    path = error_sidecar_for(txt_path)
    prior = 0
    if path.exists():
        try:
            prior = int(json.loads(path.read_text()).get("attempts", 0))
        except (OSError, ValueError):
            prior = 0
    data = {
        "schema": ERROR_SIDECAR_SCHEMA,
        "model": model,
        "error_class": error_class,
        "finish_reason": finish_reason,
        "attempts": prior + 1,
        "last_attempt": _utc_now_iso(),
        "message": message,
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/names/test_extractor.py -k "error_sidecar_for or write_error_sidecar" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/extractor.py tests/names/test_extractor.py
git commit -m "feat: add error-sidecar path and atomic writer for names failures"
```

---

## Task 4: Write the error sidecar on persistent failure; clear on success

**Files:**
- Modify: `src/vtextract/names/extractor.py` — the `run()` result handler (~`extractor.py:204-215`)
- Test: `tests/names/test_extractor.py`

Context: the success/transient behavior at `extractor.py:206-213` must be preserved. We only add a branch for persistent failures and an unlink-on-success.

- [ ] **Step 1: Write the failing test**

Add to `tests/names/test_extractor.py`:

```python
def test_persistent_failure_writes_error_sidecar(tmp_path):
    from vtextract.names.extractor import extract, error_sidecar_for, sidecar_for
    from vtextract.names.llm import TruncatedResponseError
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None):
        raise TruncatedResponseError(
            "response truncated at output-token limit (finish_reason=length)",
            finish_reason="length")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed_persistent == 2
    assert stats.failed == 0
    err = error_sidecar_for(archive / "pages" / "100" / "a.jpg.txt")
    assert err.exists()
    assert json.loads(err.read_text())["error_class"] == "truncated"
    # no success sidecar written
    assert not sidecar_for(archive / "pages" / "100" / "a.jpg.txt").exists()


def test_transient_failure_writes_no_error_sidecar(tmp_path):
    from vtextract.names.extractor import extract, error_sidecar_for
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None):
        raise ConnectionError("connection refused")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed == 2
    assert stats.failed_persistent == 0
    assert not error_sidecar_for(archive / "pages" / "100" / "a.jpg.txt").exists()


def test_success_removes_stale_error_sidecar(tmp_path):
    from vtextract.names.extractor import (
        extract, error_sidecar_for, _write_error_sidecar)
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="old")
    assert error_sidecar_for(txt).exists()
    # force so the page is reprocessed even though no success sidecar exists yet
    extract(archive, model="m", find=_fake_find_factory({}), force=True,
            show_progress=False)
    assert not error_sidecar_for(txt).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/names/test_extractor.py -k "persistent_failure or transient_failure or removes_stale" -v`
Expected: FAIL — `AttributeError: ... 'failed_persistent'` is already defined (Task 1), so the real failure is the assertions on the error sidecar / counters not being written yet.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/names/extractor.py`, replace the result-handling block inside `run()` (currently ~`extractor.py:206-213`):

```python
                txt, people, usage, elapsed_ms, exc = fut.result()
                if people is None:
                    cls = llm_module.error_class(exc) if exc else None
                    if cls is not None:
                        _write_error_sidecar(
                            txt, model=model, error_class=cls,
                            finish_reason=llm_module.truncation_finish_reason(exc),
                            message=llm_module.friendly_error(exc, model, api_base))
                        stats.failed_persistent += 1
                    else:
                        stats.failed += 1
                    _log_failure(progress, txt, exc, model, api_base)
                else:
                    _write_sidecar_atomic(sidecar_for(txt), model, people, usage,
                                          elapsed_ms)
                    error_sidecar_for(txt).unlink(missing_ok=True)
                    stats.extracted += 1
                    stats.people += len(people)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/names/test_extractor.py -v`
Expected: PASS (whole file, including the pre-existing `test_extract_failure_leaves_no_sidecar` — its `RuntimeError("model down")` is transient, so behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/extractor.py tests/names/test_extractor.py
git commit -m "feat: park persistent names failures in an error sidecar, clear on success"
```

---

## Task 5: Skip parked pages; `--retry-failed` re-attempts them

**Files:**
- Modify: `src/vtextract/names/extractor.py` — `extract()` signature + the todo-selection loop (~`extractor.py:147-184`); update the docstring
- Test: `tests/names/test_extractor.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/names/test_extractor.py`:

```python
def test_parked_page_skipped_on_normal_run(tmp_path):
    from vtextract.names.extractor import extract, sidecar_for, _write_error_sidecar
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="old")

    def fail_if_called(chunk_text, model, api_base=None):
        raise AssertionError("parked page must not be re-attempted")

    stats = extract(archive, model="m", find=fail_if_called, show_progress=False)
    # a.jpg is parked (skipped); b.jpg has no sidecar and is processed
    assert stats.parked == 1
    assert not sidecar_for(txt).exists()


def test_retry_failed_reattempts_parked_page(tmp_path):
    from vtextract.names.extractor import (
        extract, sidecar_for, error_sidecar_for, _write_error_sidecar)
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="old")
    stats = extract(archive, model="m", find=_fake_find_factory({}),
                    retry_failed=True, show_progress=False)
    assert stats.parked == 0
    assert sidecar_for(txt).exists()            # now succeeded
    assert not error_sidecar_for(txt).exists()  # stale error cleared


def test_skip_as_done_clears_orphan_error_sidecar(tmp_path):
    from vtextract.names.extractor import (
        extract, sidecar_for, error_sidecar_for, _write_error_sidecar)
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    # both a success sidecar AND a stale error sidecar exist for the same page
    extract(archive, model="m", find=_fake_find_factory({}), show_progress=False)
    _write_error_sidecar(txt, model="m", error_class="bad_json",
                         finish_reason=None, message="stale")
    assert error_sidecar_for(txt).exists()
    stats = extract(archive, model="m", find=_fake_find_factory({}),
                    show_progress=False)
    assert stats.skipped == 2
    assert not error_sidecar_for(txt).exists()  # success wins, orphan removed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/names/test_extractor.py -k "parked_page or retry_failed_reattempts or skip_as_done" -v`
Expected: FAIL — `TypeError: extract() got an unexpected keyword argument 'retry_failed'` / parked counter never set.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/names/extractor.py`, add the parameter to `extract()` (insert after `force: bool = False,` ~`extractor.py:157`):

```python
    retry_failed: bool = False,
```

Update the docstring sentence to read:

```python
    """Walk page transcriptions, extract people, write/refresh sidecars.

    Skips pages whose success sidecar already exists unless ``force``. Pages with
    a persistent-error sidecar are skipped (parked) unless ``force`` or
    ``retry_failed``. ``scope_pages``, when given, limits work to those
    (root_id, page_key) pairs. A page whose extraction fails transiently is left
    without a sidecar so a later run retries it; a persistent failure is parked.
    """
```

Replace the todo-selection loop (currently ~`extractor.py:177-184`):

```python
    for root_id, page_key, txt in page_transcriptions(archive):
        if scope_pages is not None and (root_id, page_key) not in scope_pages:
            continue
        side = sidecar_for(txt)
        if side.exists() and not force:
            stats.skipped += 1
            error_sidecar_for(txt).unlink(missing_ok=True)  # success wins
            continue
        if error_sidecar_for(txt).exists() and not force and not retry_failed:
            stats.parked += 1
            continue
        todo.append((page_key, txt))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/names/test_extractor.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/extractor.py tests/names/test_extractor.py
git commit -m "feat: skip parked names pages unless --retry-failed/--force"
```

---

## Task 6: `iter_error_sidecars` listing helper

**Files:**
- Modify: `src/vtextract/names/extractor.py` — add `ErrorRecord` dataclass + `iter_error_sidecars` (place near `page_transcriptions` ~`extractor.py:37-50`; add `from dataclasses import dataclass` import)
- Test: `tests/names/test_extractor.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/names/test_extractor.py`:

```python
def test_iter_error_sidecars_returns_records(tmp_path):
    from vtextract.names.extractor import iter_error_sidecars, _write_error_sidecar
    archive = _make_archive(tmp_path)
    _write_error_sidecar(archive / "pages" / "100" / "a.jpg.txt", model="m",
                         error_class="truncated", finish_reason="length",
                         message="cut off")
    records = iter_error_sidecars(archive)
    assert len(records) == 1
    rec = records[0]
    assert rec.root_id == "100"
    assert rec.page_key == "a.jpg"
    assert rec.error_class == "truncated"
    assert rec.attempts == 1
    assert rec.message == "cut off"


def test_iter_error_sidecars_honours_scope(tmp_path):
    from vtextract.names.extractor import iter_error_sidecars, _write_error_sidecar
    archive = _make_archive(tmp_path)
    for key in ("a.jpg", "b.jpg"):
        _write_error_sidecar(archive / "pages" / "100" / f"{key}.txt", model="m",
                             error_class="bad_json", finish_reason=None, message="x")
    scoped = iter_error_sidecars(archive, scope_pages={("100", "a.jpg")})
    assert {r.page_key for r in scoped} == {"a.jpg"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/names/test_extractor.py -k "iter_error_sidecars" -v`
Expected: FAIL — `ImportError: cannot import name 'iter_error_sidecars'`.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/names/extractor.py`, add to the imports near the top:

```python
from dataclasses import dataclass
```

Add after `page_transcriptions` (~`extractor.py:50`):

```python
@dataclass(frozen=True)
class ErrorRecord:
    """One parsed persistent-failure sidecar, for listing."""
    root_id: str
    page_key: str
    error_class: str
    finish_reason: str | None
    attempts: int
    last_attempt: str
    message: str
    model: str


def iter_error_sidecars(
    archive: Path, scope_pages: set[tuple[str, str]] | None = None,
) -> list[ErrorRecord]:
    """Parse every {page_key}.names.error.json under archive/pages.

    ``scope_pages``, when given, limits the result to those (root_id, page_key)
    pairs. Malformed files are skipped (a half-written sidecar shouldn't crash a
    listing).
    """
    out: list[ErrorRecord] = []
    pages_dir = Path(archive) / "pages"
    if not pages_dir.is_dir():
        return out
    for err in sorted(pages_dir.glob("*/*.jpg.names.error.json")):
        root_id = err.parent.name
        page_key = err.name[: -len(_ERROR_SUFFIX)]  # keeps trailing .jpg
        if scope_pages is not None and (root_id, page_key) not in scope_pages:
            continue
        try:
            data = json.loads(err.read_text())
        except (OSError, ValueError):
            continue
        out.append(ErrorRecord(
            root_id=root_id,
            page_key=page_key,
            error_class=str(data.get("error_class", "")),
            finish_reason=data.get("finish_reason"),
            attempts=int(data.get("attempts", 0)),
            last_attempt=str(data.get("last_attempt", "")),
            message=str(data.get("message", "")),
            model=str(data.get("model", "")),
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/names/test_extractor.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/extractor.py tests/names/test_extractor.py
git commit -m "feat: add iter_error_sidecars listing helper for names failures"
```

---

## Task 7: CLI `--retry-failed` + summary + exit code

**Files:**
- Modify: `src/vtextract/cli.py` — `_run_names` (~`cli.py:557-609`): add the flag, pass it through, update the summary line and exit code; update the parser `description`
- Test: `tests/test_cli_names.py`

Context: the test seam for the LLM in CLI tests is `_make_find()` (see `cli.py:600`); CLI tests monkeypatch `cli._make_find`. The file already has `_archive_with_page(tmp_path) -> (archive, cfg)` (`tests/test_cli_names.py:12-18`), which writes an inline `vt.toml` (`[names]\nmodel = "test/model"`) and a page; reuse it. Pass `--archive str(archive) --config str(cfg)`. The test below asserts wiring, not real extraction — it patches `names_extractor.extract`. Note the `cli` and `names_extractor` modules are imported at the top of `cli.py` as `from vtextract.names import extractor as names_extractor`; in the test, import via `from vtextract.cli import names_extractor` or `from vtextract.names import extractor as names_extractor` (same module object).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_names.py` (the file already imports `from vtextract import cli`):

```python
def test_names_retry_failed_flag_passed_through(tmp_path, monkeypatch):
    from vtextract.names import extractor as names_extractor

    archive, cfg = _archive_with_page(tmp_path)
    captured = {}

    def fake_extract(arch, **kwargs):
        captured.update(kwargs)
        return names_extractor.NamesStats()

    monkeypatch.setattr(names_extractor, "extract", fake_extract)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--retry-failed"])
    assert rc == 0
    assert captured["retry_failed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_names.py -k "retry_failed_flag" -v`
Expected: FAIL — `KeyError: 'retry_failed'` (flag not wired) or argparse error for the unknown option.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/cli.py`, update the `_run_names` parser `description` (~`cli.py:561-563`) to mention parking:

```python
        description="Extract people from page transcriptions into per-page "
        "'.names.json' sidecars using an LLM. Resumable: skips pages that "
        "already have a sidecar (use --force to re-extract). Persistent "
        "failures (truncation / bad JSON) are parked in a "
        "'.names.error.json' sidecar; re-attempt them with --retry-failed.",
```

Add the flag next to `--force` (~`cli.py:577-578`):

```python
    parser.add_argument("--retry-failed", action="store_true",
                        help="Re-attempt pages parked with a persistent-error "
                             "sidecar (.names.error.json).")
```

Pass it through to `extract` (~`cli.py:596-602`), adding the kwarg:

```python
        workers=workers, find=_make_find(), force=args.force,
        retry_failed=args.retry_failed,
        scope_pages=scope_pages,
```

Replace the summary print + return (~`cli.py:603-609`):

```python
    print(
        f"names: {stats.extracted} extracted, {stats.skipped} skipped, "
        f"{stats.parked} parked, {stats.failed_persistent} new persistent "
        f"error(s), {stats.failed} transient failure(s) ({stats.people} people). "
        f"Run `vtindex build --archive {archive}` to index them.",
        file=sys.stderr,
    )
    if stats.parked or stats.failed_persistent:
        print("Re-run parked pages with --retry-failed "
              "(or inspect them with --list-failed).", file=sys.stderr)
    return 1 if (stats.failed or stats.failed_persistent) else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_names.py -v`
Expected: PASS (whole file — confirms the changed summary/exit code didn't break existing CLI tests; adjust any existing test that asserted the exact old summary string to the new wording).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/cli.py tests/test_cli_names.py
git commit -m "feat: wire names --retry-failed and report parked failures in summary"
```

---

## Task 8: CLI `--list-failed` view

**Files:**
- Modify: `src/vtextract/cli.py` — `_run_names`: add the flag and a no-extraction branch that renders a table via `iter_error_sidecars`; add a `rich.table` import if not present
- Test: `tests/test_cli_names.py`

Context: the branch must run BEFORE model resolution (`model = args.model or config.names.model` ~`cli.py:594`) so listing never needs a model. It still honours `args.identifiers` scoping (reuse the `scope_pages` block ~`cli.py:586-592`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_names.py`:

```python
def test_names_list_failed_prints_rows_without_llm(tmp_path, monkeypatch, capsys):
    from vtextract.names import extractor as names_extractor

    archive, cfg = _archive_with_page(tmp_path)

    def fail_if_called():
        raise AssertionError("--list-failed must not build a find/LLM seam")

    monkeypatch.setattr(cli, "_make_find", fail_if_called)
    names_extractor._write_error_sidecar(
        archive / "pages" / "100" / "a.jpg.txt", model="m",
        error_class="truncated", finish_reason="length", message="cut off")
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--list-failed"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "a.jpg" in out
    assert "truncated" in out


def test_names_list_failed_empty_is_clean(tmp_path, capsys):
    archive, cfg = _archive_with_page(tmp_path)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--list-failed"])
    assert rc == 0
    assert "no parked" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_names.py -k "list_failed" -v`
Expected: FAIL — argparse error for unknown `--list-failed`.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/cli.py`, ensure these imports exist near the top of the file (add only what's missing):

```python
from rich.console import Console
from rich.table import Table
```

Add the flag next to `--retry-failed`:

```python
    parser.add_argument("--list-failed", action="store_true",
                        help="List pages parked with a persistent-error sidecar "
                             "and exit (no extraction).")
```

Insert the listing branch in `_run_names` immediately AFTER the `scope_pages`
block (after ~`cli.py:592`, before `model = args.model or ...`):

```python
    if args.list_failed:
        records = names_extractor.iter_error_sidecars(archive, scope_pages)
        if not records:
            print("no parked failures", file=sys.stdout)
            return 0
        table = Table(title=f"parked names failures ({len(records)})")
        table.add_column("page")
        table.add_column("class")
        table.add_column("tries", justify="right")
        table.add_column("when")
        table.add_column("message")
        for r in records:
            when = r.last_attempt[:10]  # YYYY-MM-DD
            msg = r.message if len(r.message) <= 60 else r.message[:57] + "..."
            table.add_row(f"{r.root_id}/{r.page_key}", r.error_class,
                          str(r.attempts), when, msg)
        Console().print(table)
        print(f"{len(records)} parked. Re-run with --retry-failed.",
              file=sys.stdout)
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_names.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/cli.py tests/test_cli_names.py
git commit -m "feat: add names --list-failed view over parked error sidecars"
```

---

## Task 9: Compatibility guard — `vtindex` ignores error sidecars

**Files:**
- Create: `tests/names/test_error_sidecar_index_compat.py`

Context: `index/builder.py:30` globs `*/*.jpg.names.json`; `*.jpg.names.error.json` ends in `.error.json` so it must not match. This test pins that so a future glob change can't silently start ingesting error sidecars as people.

- [ ] **Step 1: Write the failing test**

Create `tests/names/test_error_sidecar_index_compat.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved
import json

from vtextract.names.extractor import _write_error_sidecar


def test_index_glob_excludes_error_sidecars(tmp_path):
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    # a real success sidecar (should be seen) ...
    (pages / "a.jpg.names.json").write_text(json.dumps(
        {"schema": 1, "model": "m", "people": []}))
    # ... and a parked-failure sidecar (must NOT be seen by the index glob)
    _write_error_sidecar(pages / "b.jpg.txt", model="m", error_class="truncated",
                         finish_reason="length", message="cut off")

    seen = sorted(p.name for p in (tmp_path / "pages").glob("*/*.jpg.names.json"))
    assert seen == ["a.jpg.names.json"]
    assert "b.jpg.names.error.json" not in seen
```

- [ ] **Step 2: Run test to verify it fails (then passes)**

Run: `uv run pytest tests/names/test_error_sidecar_index_compat.py -v`
Expected: PASS immediately — this is a characterization test pinning existing-safe behavior (no production change needed). If it FAILS, the glob is broader than assumed; stop and reconcile before proceeding.

- [ ] **Step 3: (no implementation needed)**

This task only adds a guard test. If Step 2 passed, continue.

- [ ] **Step 4: Re-run to confirm**

Run: `uv run pytest tests/names/test_error_sidecar_index_compat.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/names/test_error_sidecar_index_compat.py
git commit -m "test: pin that vtindex ingestion ignores names error sidecars"
```

---

## Task 10: README + full suite

**Files:**
- Modify: `README.md` (the `names` section)
- Verify: whole test suite

- [ ] **Step 1: Update README**

Find the `vtextract names` documentation in `README.md` and add a short subsection describing the new behavior. Use this text (place it after the existing `names` usage description; match surrounding heading depth):

```markdown
#### Failed pages

A page whose extraction fails *deterministically* — the model's output was
truncated at the token cap (a repetition loop) or it never returned valid JSON
even after a retry — is *parked*: a `{page_key}.names.error.json` sidecar is
written next to the transcription recording the error class, attempt count and
the provider message. Parked pages are **skipped** by normal re-runs (so they
don't burn tokens every time) and the run's summary reports how many are parked.

- `vtextract names --list-failed [--archive PATH] [refcodes/ids...]` lists parked
  pages (page, error class, attempts, date, message) without calling the LLM.
- `vtextract names --retry-failed [...]` re-attempts parked pages (e.g. after
  switching `--model` or lowering `[names].chunk_size`). `--force` also retries
  them. A successful extraction removes the page's error sidecar.

Transient failures (rate-limit, auth, network, model-not-found) are **not**
parked — they are logged and retried on the next run, as before.
```

- [ ] **Step 2: Commit the docs**

```bash
git add README.md
git commit -m "docs: document names parked-failure workflow (--list-failed/--retry-failed)"
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest`
Expected: PASS — all tests green (previous count was 579; this plan adds ~16 tests). If anything fails, fix before declaring done.

- [ ] **Step 4: Smoke-check the CLI help**

Run: `uv run vtextract names --help`
Expected: shows `--retry-failed` and `--list-failed` in the options, and the updated description mentioning parking.

- [ ] **Step 5: Final commit (if Step 4 surfaced any tweak)**

```bash
git add -A
git commit -m "chore: finalize names failure-records feature"
```

---

## Self-Review notes

- **Spec coverage:** error-sidecar format (Task 3), classifier seam (Task 2), `extract()` resume table + write/cleanup (Tasks 4–5), `NamesStats`/summary/`--retry-failed`/`--list-failed` (Tasks 1, 7, 8), compatibility guard (Task 9), README (Task 10). All spec sections map to a task.
- **Type consistency:** `error_class`/`is_persistent_failure`/`truncation_finish_reason` (Task 2) are the exact names used in Task 4; `error_sidecar_for`/`_write_error_sidecar` (Task 3) reused verbatim in Tasks 4–6, 8–9; `ErrorRecord` fields (Task 6) match the table rendering (Task 8); `NamesStats` fields `parked`/`failed`/`failed_persistent` (Task 1) match the result handler (Task 4) and summary (Task 7).
- **No placeholders:** every code step shows full code; test steps show full test bodies. The only judgement call is reusing the existing config-file helper in `tests/test_cli_names.py` (Task 7/8 Step 1), which is called out explicitly.
