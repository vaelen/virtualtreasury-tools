# vtextract Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all seven non-blocking follow-ups from `TODO.md` — three behavior/robustness changes, one resume-integrity change, and three test-coverage gaps.

**Architecture:** Each item is small and localized. Source changes touch `cli.py` (exit code, arg validation), `schema.py` (friendlier error), and `archive.py` (checksum re-verification on resume). Test-only items add coverage for CLI-level resume, throttle/backoff timing, and empty-canvas manifests. Every change follows the existing TDD pattern: failing test against committed fixtures or synthetic data via `httpx.MockTransport`, then minimal implementation.

**Tech Stack:** Python 3, pytest, httpx (`MockTransport`), dataclasses. Tests run entirely offline against `docs/examples/` fixtures.

---

## File Structure

- `src/vtextract/cli.py` — add numeric-arg validation (`_positive_int`, `_nonneg_int` type functions) and change `run`'s return to be non-zero on partial failure. No new responsibilities.
- `src/vtextract/schema.py` — `loris_filename` raises a clear `ValueError` instead of `IndexError` for non-Loris URLs. Still pure, no I/O.
- `src/vtextract/archive.py` — `has_page` re-verifies the on-disk image against the recorded `sha256`, returning `False` (→ re-fetch) on mismatch or missing file. Keeps the on-disk store as its single responsibility.
- `tests/test_cli.py` — add partial-failure exit-code test, arg-validation tests, and a two-run resume test.
- `tests/test_schema.py` — add non-Loris URL test.
- `tests/test_archive.py` — add corrupt/missing-file re-verification tests.
- `tests/test_client.py` — add throttle-delay and backoff-growth timing tests.
- `tests/test_fetcher.py` — add empty-canvas manifest test.

A note on running tests: use `.venv/bin/python -m pytest` (the system `python3` has no pytest).

---

### Task 1: Friendlier error for non-Loris image URLs

**Files:**
- Modify: `src/vtextract/schema.py:22-25` (`loris_filename`)
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_schema.py` (the file already imports `pytest` and `loris_filename`):

```python
def test_loris_filename_rejects_non_loris_url():
    with pytest.raises(ValueError, match="loris"):
        loris_filename("https://example.test/full/full/0/default.jpg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schema.py::test_loris_filename_rejects_non_loris_url -v`
Expected: FAIL — raises `IndexError`, not `ValueError`, so `pytest.raises(ValueError)` does not catch it.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `loris_filename` in `src/vtextract/schema.py`:

```python
def loris_filename(image_url: str) -> str:
    """Pull the Loris page identifier out of a full image URL."""
    parts = image_url.split("/loris/", 1)
    if len(parts) != 2:
        raise ValueError(f"Image URL is not a Loris URL (no '/loris/'): {image_url}")
    return unquote(parts[1].split("/", 1)[0])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: PASS — the new test plus all existing schema tests (e.g. `test_loris_filename_from_image_url`) still pass.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/schema.py tests/test_schema.py
git commit -m "fix: raise clear ValueError for non-Loris image URLs"
```

---

### Task 2: CLI exit code on partial failure

**Files:**
- Modify: `src/vtextract/cli.py:81-82` (end of `run`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (the file already imports `httpx` and `cli`):

```python
def test_run_returns_nonzero_when_a_resource_fails(tmp_path, monkeypatch):
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/IR_REST_V2/webapi/doc_search":
            return httpx.Response(200, json=search_response)
        # Detail call 404s -> fetch_resource raises -> run records a failure.
        return httpx.Response(404, text=path)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))

    exit_code = cli.run(
        ["https://virtualtreasury.ie/search-results?kwList=houston",
         "--out", str(tmp_path), "--context-pages", "0"],
        env={"VT_AUTH": "x", "VT_DELAY": "0", "VT_MAX_RETRIES": "0"},
    )
    assert exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_run_returns_nonzero_when_a_resource_fails -v`
Expected: FAIL — `run` currently returns `0` even though one resource failed; assert sees `0 == 1`.

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/cli.py`, change the final return of `run`:

```python
    print(f"finished: {completed} archived, {failed} failed")
    return 1 if failed else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS — the new test returns `1`; the existing `test_run_archives_results_end_to_end` still returns `0` (no failures).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/cli.py tests/test_cli.py
git commit -m "feat: return non-zero exit code on partial failure"
```

---

### Task 3: Validate CLI numeric args

**Files:**
- Modify: `src/vtextract/cli.py:23-38` (`build_parser`, plus two new module-level helpers)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (add `import pytest` at the top of the file if not already present):

```python
def test_page_size_rejects_zero():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["https://virtualtreasury.ie/search-results?kwList=x",
             "--out", "out", "--page-size", "0"]
        )


def test_context_pages_rejects_negative():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["https://virtualtreasury.ie/search-results?kwList=x",
             "--out", "out", "--context-pages", "-1"]
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_page_size_rejects_zero tests/test_cli.py::test_context_pages_rejects_negative -v`
Expected: FAIL — argparse currently accepts `0` and `-1` (no `SystemExit` raised).

- [ ] **Step 3: Write minimal implementation**

In `src/vtextract/cli.py`, add two helpers above `build_parser` (after `_make_transport`):

```python
def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def _nonneg_int(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n
```

Then change the two affected arguments in `build_parser` to use them:

```python
    parser.add_argument(
        "--context-pages", type=_nonneg_int, default=1,
        help="Neighbouring physical pages to also fetch per page (default 1).",
    )
    parser.add_argument(
        "--page-size", type=_positive_int, default=100,
        help="doc_search page size (default 100).",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS — both new tests raise `SystemExit`; the end-to-end test (which passes `--context-pages 0`, a valid non-negative value) still passes.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/cli.py tests/test_cli.py
git commit -m "feat: reject nonsensical --page-size and --context-pages values"
```

---

### Task 4: Checksum verification on resume

**Files:**
- Modify: `src/vtextract/archive.py:44-45` (`has_page`)
- Test: `tests/test_archive.py`

**Why this is safe:** `has_page` is called only by `fetcher._ensure_page` to decide whether to skip a page. Returning `False` for a corrupt or missing on-disk file makes the fetcher re-download and re-store it. `store_page` always writes the file before recording its checksum, so the existing `test_store_page_writes_files_and_registers` (which asserts `has_page` is `True` right after `store_page`) keeps passing.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_archive.py` (the file already imports `hashlib`):

```python
def test_has_page_false_when_file_corrupted(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg",
                       image_bytes=b"abc", text=None, annotations=None)
    assert archive.has_page("208925", "p1.jpg") is True
    (tmp_path / "pages" / "208925" / "p1.jpg").write_bytes(b"corrupted")
    assert archive.has_page("208925", "p1.jpg") is False


def test_has_page_false_when_file_missing(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg",
                       image_bytes=b"abc", text=None, annotations=None)
    (tmp_path / "pages" / "208925" / "p1.jpg").unlink()
    assert archive.has_page("208925", "p1.jpg") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_archive.py::test_has_page_false_when_file_corrupted tests/test_archive.py::test_has_page_false_when_file_missing -v`
Expected: FAIL — current `has_page` only checks the state dict, so it returns `True` for both the corrupted and the deleted file.

- [ ] **Step 3: Write minimal implementation**

Replace `has_page` in `src/vtextract/archive.py`:

```python
    def has_page(self, root_id: str, page_key: str) -> bool:
        entry = self._state["pages"].get(f"{root_id}/{page_key}")
        if not entry:
            return False
        path = self.root / "pages" / root_id / page_key
        if not path.exists():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
```

(`hashlib` is already imported at the top of `archive.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_archive.py tests/test_fetcher.py -v`
Expected: PASS — new tests pass; existing archive and fetcher tests (including `test_fetch_resource_skips_already_stored_page`, which relies on `has_page` being `True` for an intact stored page) still pass.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/archive.py tests/test_archive.py
git commit -m "fix: re-verify stored page checksum in has_page so resume re-fetches corrupt images"
```

---

### Task 5: Empty-canvas manifest test

**Files:**
- Test: `tests/test_fetcher.py` (no source change — this verifies existing behavior holds)

- [ ] **Step 1: Write the test**

Add to `tests/test_fetcher.py` (the file already imports `httpx`, `Client`, and `fetch_resource`, and defines `_item_json`):

```python
def test_fetch_resource_empty_manifest_completes_with_no_pages(tmp_path):
    from vtextract.archive import Archive

    empty_manifest = {"sequences": [{"canvases": []}]}
    calls = {"loris": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, json=empty_manifest)
        if "/loris/" in path:
            calls["loris"] += 1
            return httpx.Response(200, content=b"\xff\xd8img")
        return httpx.Response(404, text=path)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    search_hit = {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}

    record = fetch_resource(client, archive, search_hit, search_id="s", context_pages=1)

    assert record.pages == []
    assert calls["loris"] == 0
    assert archive.is_resource_complete(474234) is True
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_fetcher.py::test_fetch_resource_empty_manifest_completes_with_no_pages -v`
Expected: PASS — `parse_manifest` returns `[]` for a zero-canvas sequence, so no image requests fire and the resource is marked complete with no pages. (This is a characterization test; it should pass without touching source. If it fails, stop and investigate before changing anything.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_fetcher.py
git commit -m "test: cover empty-canvas manifest (completes with no pages, no image requests)"
```

---

### Task 6: Resume across runs (CLI level)

**Files:**
- Test: `tests/test_cli.py` (no source change — verifies the resume path in `cli.run`)

- [ ] **Step 1: Write the test**

Add to `tests/test_cli.py`:

```python
def test_run_twice_skips_completed_resource(tmp_path, monkeypatch):
    from pathlib import Path
    examples = Path(__file__).resolve().parent.parent / "docs" / "examples"

    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}
        ],
    }
    counts = {"item": 0, "loris": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/IR_REST_V2/webapi/doc_search":
            return httpx.Response(200, json=search_response)
        if path == "/rest/isadg-identity-statements/474234":
            counts["item"] += 1
            return httpx.Response(200, content=(examples / "item" / "isadg-identity-statements" / "response.json").read_bytes())
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=(examples / "item" / "manifest" / "response.json").read_bytes())
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=(examples / "item" / "list" / "response.json").read_bytes())
        if path.startswith("/loris/"):
            counts["loris"] += 1
            return httpx.Response(200, content=(examples / "item" / "loris" / "response.jpg").read_bytes())
        return httpx.Response(404, text=path)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))

    argv = ["https://virtualtreasury.ie/search-results?kwList=houston",
            "--out", str(tmp_path), "--context-pages", "0"]
    env = {"VT_AUTH": "x", "VT_DELAY": "0"}

    # First run populates the archive and fetches the item.
    assert cli.run(argv, env=env) == 0
    assert counts["item"] == 1
    assert counts["loris"] == 1

    # Second run should skip the already-complete resource: no item or image calls.
    counts["item"] = 0
    counts["loris"] = 0
    assert cli.run(argv, env=env) == 0
    assert counts["item"] == 0
    assert counts["loris"] == 0
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_run_twice_skips_completed_resource -v`
Expected: PASS — the first run writes `_state.json` marking 474234 complete; the second `Archive` instance reads that state, so `run` prints `skip` and never calls `fetch_resource`. (Characterization test; passes without source changes. If it fails, investigate the resume path before editing.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: cover CLI-level resume (second run skips completed resource)"
```

---

### Task 7: Throttle / backoff timing

**Files:**
- Test: `tests/test_client.py` (no source change — verifies `_throttle` and `_request` backoff timing)

- [ ] **Step 1: Write the tests**

Add to `tests/test_client.py` (the file already imports `httpx` and `Client`). Note: `make_client` hardcodes `delay=0.0` and a no-op `sleep_func`, so these tests construct `Client` directly to capture sleep calls:

```python
def test_throttle_sleeps_between_consecutive_requests():
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = Client(
        base_url="https://api.test", auth_header="Basic x", user_agent="UA",
        transport=httpx.MockTransport(handler), delay=0.05, sleep_func=slept.append,
    )
    client.get_json("/a")  # first request: no wait (no prior request)
    client.get_json("/b")  # second request: must wait out the delay
    assert any(s > 0 for s in slept)


def test_backoff_grows_per_retry():
    slept: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    client = Client(
        base_url="https://api.test", auth_header="Basic x", user_agent="UA",
        transport=httpx.MockTransport(handler), delay=0.0, max_retries=3,
        sleep_func=slept.append,
    )
    assert client.get_json("/x") == {"ok": True}
    # delay=0.0 means _throttle never sleeps, so these are pure backoff waits:
    # 2**0 after the first 500, 2**1 after the second.
    assert slept == [1.0, 2.0]
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_client.py -v`
Expected: PASS — `_throttle` sleeps the remaining delay before the second request; `_request` sleeps `2.0**attempt` (1.0 then 2.0) between the two 500s and the final 200. (Characterization tests for existing behavior; they should pass without source changes.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_client.py
git commit -m "test: cover throttle delay and exponential backoff timing"
```

---

## Final Verification

- [ ] **Run the full suite:**

Run: `.venv/bin/python -m pytest`
Expected: PASS — all existing and new tests green, no network access.

- [ ] **Update `TODO.md`:** check off (or remove) all seven completed items, then commit:

```bash
git add TODO.md
git commit -m "docs: mark follow-ups complete in TODO.md"
```

---

## Self-Review Notes

- **Spec coverage:** All seven `TODO.md` items map to a task — exit code (T2), checksum verify (T4), resume test (T6), backoff/throttle test (T7), empty-canvas test (T5), non-Loris error (T1), arg validation (T3).
- **Type/name consistency:** `_positive_int`/`_nonneg_int` (T3) used exactly as defined; `has_page` signature unchanged (T4); `loris_filename` return type unchanged (T1).
- **No placeholders:** every code and test step shows complete, runnable content.
- **Tasks 5–7 are characterization tests** of existing behavior (no source change expected). They still follow write-then-run, but if any fails on first run, that is a real finding — stop and investigate rather than editing source to force a pass.
