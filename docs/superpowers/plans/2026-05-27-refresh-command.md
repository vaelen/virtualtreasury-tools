# Refresh Command + `--refresh` Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `refresh` command (and `--refresh` flags on `search`/`get`) that re-fetches item metadata for already-archived resources and HEAD-verifies each image's byte size against disk, re-downloading mismatched or missing images.

**Architecture:** Thread a single `refresh: bool` through the existing fetch path (`_extract → fetch_resource → _ensure_page`). A new `client.head()` returns Content-Length; in refresh mode `_ensure_page` verifies the on-disk size and only re-downloads on mismatch/missing. The `refresh` command enumerates every archived item and runs the same `_extract(refresh=True)` once, behind a confirmation gate.

**Tech Stack:** Python 3, `uv`, `pytest`, `httpx.MockTransport`, `rich`. Spec: `docs/superpowers/specs/2026-05-27-refresh-command-design.md`.

**Conventions:** TDD (write failing test, see it fail, implement minimally, see it pass, commit). Tests run against committed fixtures / `MockTransport` only — never the network. Run tests with `uv run pytest`. End every commit message body with the trailer:
`Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

---

### Task 1: `client.head()`

**Files:**
- Modify: `src/vtextract/client.py` (add a method after `get_bytes`, ~line 74)
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` (uses the existing `make_client` helper):

```python
def test_head_returns_content_length_int():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"content-length": "2003189"})

    client = make_client(handler)
    assert client.head("https://api.test/loris/x/full/full/0/default.jpg") == 2003189


def test_head_returns_none_when_no_content_length():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)  # no content-length header

    client = make_client(handler)
    assert client.head("https://api.test/loris/x") is None


def test_head_retries_on_503_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, headers={"content-length": "5"})

    client = make_client(handler)  # make_client passes sleep_func=lambda _s: None
    assert client.head("https://api.test/loris/x") == 5
    assert calls["n"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -k head -v`
Expected: FAIL — `AttributeError: 'Client' object has no attribute 'head'`.

- [ ] **Step 3: Implement**

In `src/vtextract/client.py`, add after `get_bytes` (line 74):

```python
    def head(self, url: str) -> int | None:
        """HEAD a URL; return its Content-Length in bytes, or None if absent."""
        response = self._request("HEAD", url)
        length = response.headers.get("content-length")
        return int(length) if length is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/client.py tests/test_client.py
git commit -m "feat: add client.head returning Content-Length"
```

---

### Task 2: `archive.page_size()`

**Files:**
- Modify: `src/vtextract/archive.py` (add after `page_checksum`, ~line 68)
- Test: `tests/test_archive.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_archive.py` (import `Archive` as the existing tests do):

```python
def test_page_size_returns_byte_size_for_existing_page(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    archive.store_page(
        root_id="r1", page_key="p1.jpg",
        image_bytes=b"\xff\xd8abc", text=None, annotations=None,
    )
    assert archive.page_size("r1", "p1.jpg") == 5


def test_page_size_returns_none_when_missing(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    assert archive.page_size("r1", "nope.jpg") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_archive.py -k page_size -v`
Expected: FAIL — `AttributeError: 'Archive' object has no attribute 'page_size'`.

- [ ] **Step 3: Implement**

In `src/vtextract/archive.py`, add after `page_checksum` (line 68):

```python
    def page_size(self, root_id: str, page_key: str) -> int | None:
        """Byte size of a stored page image on disk, or None if absent."""
        path = self.root / "pages" / root_id / page_key
        return path.stat().st_size if path.exists() else None
```

(Uses `self.root` directly rather than `_page_dir`, which would create the directory as a side effect.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_archive.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/archive.py tests/test_archive.py
git commit -m "feat: add archive.page_size for on-disk image byte size"
```

---

### Task 3: Refresh-aware page handling in `fetcher.py`

**Files:**
- Modify: `src/vtextract/fetcher.py` (`fetch_resource` signature + work loop; `_ensure_page`; add `_download_page` and `_verify_or_redownload`)
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_fetcher.py` (the file already imports `httpx`, `Client`, `fetch_resource`, `json`, and defines `_item_json`, `_item_image`, `_handler`). Add a refresh-capable counting client helper and tests:

```python
def _refresh_client(calls, *, head_len):
    """Client whose handler counts HEAD/GET on /loris/ and answers item routes.

    head_len: the Content-Length the HEAD response advertises for the image.
    """
    img = _item_image()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/loris/") and request.method == "HEAD":
            calls["head"] += 1
            headers = {} if head_len is None else {"content-length": str(head_len)}
            return httpx.Response(200, headers=headers)
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=_item_json("manifest"))
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/"):  # GET
            calls["get"] += 1
            return httpx.Response(200, content=img)
        return httpx.Response(404, text=path)

    return Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )


def test_refresh_verifies_without_redownload_when_size_matches(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    img_len = len(_item_image())

    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0)
    assert calls == {"head": 0, "get": 1}  # initial archive: one image GET, no HEAD

    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True)
    assert calls == {"head": 1, "get": 0}  # size matches: HEAD only, no re-download


def test_refresh_redownloads_on_size_mismatch(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=0), archive, hit,
                   search_id="s", context_pages=0)

    calls = {"head": 0, "get": 0}
    outcomes = []
    fetch_resource(_refresh_client(calls, head_len=len(_item_image()) + 1), archive, hit,
                   search_id="s", context_pages=0, refresh=True,
                   on_verify=lambda outcome, path: outcomes.append(outcome))
    assert calls == {"head": 1, "get": 1}  # HEAD said different size -> re-download
    assert outcomes == ["mismatch"]


def test_refresh_downloads_missing_image_without_head(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=0), archive, hit,
                   search_id="s", context_pages=0)
    # delete the image file on disk -> "missing"
    (tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg").unlink()

    calls = {"head": 0, "get": 0}
    outcomes = []
    fetch_resource(_refresh_client(calls, head_len=999), archive, hit,
                   search_id="s", context_pages=0, refresh=True,
                   on_verify=lambda o, p: outcomes.append(o))
    assert calls == {"head": 0, "get": 1}  # missing -> download, no HEAD
    assert outcomes == ["missing"]


def test_refresh_unverified_when_no_content_length(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=0), archive, hit,
                   search_id="s", context_pages=0)

    calls = {"head": 0, "get": 0}
    outcomes = []
    fetch_resource(_refresh_client(calls, head_len=None), archive, hit,
                   search_id="s", context_pages=0, refresh=True,
                   on_verify=lambda o, p: outcomes.append(o))
    assert calls == {"head": 1, "get": 0}  # no content-length -> unverified, file untouched
    assert outcomes == ["unverified"]


def test_refresh_dedupes_verified_pages_across_calls(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    img_len = len(_item_image())
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0)

    verified: set[str] = set()
    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True, _verified_pages=verified)
    assert calls["head"] == 1
    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True, _verified_pages=verified)
    assert calls["head"] == 0  # page already verified this run -> not re-HEADed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetcher.py -k refresh -v`
Expected: FAIL — `fetch_resource()` got an unexpected keyword argument `refresh`.

- [ ] **Step 3: Implement — refactor download into a helper**

In `src/vtextract/fetcher.py`, replace the body of `_ensure_page` (currently lines ~108-147) with the refresh-aware version, and add two module-level helpers. First, add `_download_page` (place it just before `_ensure_page`):

```python
def _download_page(client: Client, archive: Archive, page: Page) -> None:
    """Download a page's image (and its annotation text, if any) into the store."""
    image_bytes = client.get_bytes(page.image_url)
    text = None
    annotations = None
    if page.annotation_list_urls:
        annotations = client.get_json(page.annotation_list_urls[0])
        text = reconstruct_text(annotations)
    archive.store_page(
        root_id=page.root_id,
        page_key=page.page_key,
        image_bytes=image_bytes,
        text=text,
        annotations=annotations,
    )


def _verify_or_redownload(client: Client, archive: Archive, page: Page) -> str:
    """HEAD-verify a page image against the on-disk size; re-download on mismatch.

    Returns the outcome: "ok" (size matched), "mismatch" (re-downloaded),
    "missing" (file absent, downloaded), or "unverified" (HEAD failed or had no
    Content-Length; file left untouched).
    """
    disk_size = archive.page_size(page.root_id, page.page_key)
    if disk_size is None:
        _download_page(client, archive, page)
        return "missing"
    try:
        head_size = client.head(page.image_url)
    except Exception:  # noqa: BLE001 - cannot verify; leave the file as-is
        return "unverified"
    if head_size is None:
        return "unverified"
    if head_size == disk_size:
        return "ok"
    _download_page(client, archive, page)
    return "mismatch"
```

Now replace `_ensure_page`:

```python
def _ensure_page(
    client: Client,
    archive: Archive,
    page: Page,
    *,
    role: str,
    refs: list[PageRef],
    refresh: bool = False,
    verified: set[str] | None = None,
    on_verify: Callable[[str, str], None] | None = None,
) -> None:
    if not page.page_key:
        return
    ref = PageRef(
        page_key=page.page_key,
        root_id=page.root_id,
        role=role,
        path=archive.page_relative_path(page.root_id, page.page_key),
        canvas_label=page.canvas_label,
        width=page.width,
        height=page.height,
    )
    # avoid duplicate refs within a single resource
    if any(r.page_key == ref.page_key for r in refs):
        return
    refs.append(ref)

    if not refresh:
        if archive.has_page(page.root_id, page.page_key):
            return
        _download_page(client, archive, page)
        return

    # refresh mode: verify (once per run) the image size against disk.
    key = f"{page.root_id}/{page.page_key}"
    if verified is not None and key in verified:
        return
    outcome = _verify_or_redownload(client, archive, page)
    if verified is not None:
        verified.add(key)
    if on_verify is not None:
        on_verify(outcome, archive.page_relative_path(page.root_id, page.page_key))
```

- [ ] **Step 4: Implement — thread `refresh` through `fetch_resource`**

In `fetch_resource` (signature starts ~line 42), add three parameters after `_root_manifest_cache`:

```python
def fetch_resource(
    client: Client,
    archive: Archive,
    search_hit: dict,
    *,
    search_id: str,
    context_pages: int = 1,
    on_item_start: Callable[[int], None] | None = None,
    on_page: Callable[[], None] | None = None,
    refresh: bool = False,
    on_verify: Callable[[str, str], None] | None = None,
    _root_manifest_cache: dict | None = None,
    _verified_pages: set[str] | None = None,
) -> Record:
```

Just below the existing `cache = ...` line (~line 62), add:

```python
    verified = _verified_pages if _verified_pages is not None else set()
```

In the work loop, change the `_ensure_page(...)` call (~line 82) to pass the new args:

```python
        for page, role in work:
            _ensure_page(
                client, archive, page, role=role, refs=page_refs,
                refresh=refresh, verified=verified, on_verify=on_verify,
            )
            if on_page is not None:
                on_page()
```

(`Callable` is already imported at the top of `fetcher.py`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: PASS (all fetcher tests, including the pre-existing non-refresh ones).

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/fetcher.py tests/test_fetcher.py
git commit -m "feat: refresh mode verifies image sizes and re-downloads mismatches"
```

---

### Task 4: `Reporter.verify_summary`

**Files:**
- Modify: `src/vtextract/progress.py` (add a method to `Reporter`, after `finish`, ~line 107)
- Test: `tests/test_progress.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_progress.py` (the existing tests construct a `Reporter` with an injected non-terminal `Console`; mirror that). Use a `rich` Console writing to a buffer:

```python
def test_verify_summary_prints_counts_and_flagged_paths():
    import io
    from rich.console import Console
    from vtextract.progress import Reporter

    buf = io.StringIO()
    reporter = Reporter(console=Console(file=buf, width=200), enabled=False)
    reporter.verify_summary(
        {"ok": 3, "mismatch": 1, "missing": 2, "unverified": 1},
        ["pages/v/a.jpg", "pages/v/b.jpg"],
    )
    out = buf.getvalue()
    assert "3 ok" in out
    assert "1 re-downloaded" in out
    assert "2 downloaded" in out
    assert "1 unverified" in out
    assert "pages/v/a.jpg" in out and "pages/v/b.jpg" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_progress.py -k verify_summary -v`
Expected: FAIL — `AttributeError: 'Reporter' object has no attribute 'verify_summary'`.

- [ ] **Step 3: Implement**

In `src/vtextract/progress.py`, add to the `Reporter` class after `finish` (~line 107):

```python
    def verify_summary(self, counts: dict[str, int], flagged: list[str]) -> None:
        """Summarise a refresh run's image-verification outcomes."""
        self._say(
            f"verified images: {counts.get('ok', 0)} ok, "
            f"{counts.get('mismatch', 0)} re-downloaded, "
            f"{counts.get('missing', 0)} downloaded (missing), "
            f"{counts.get('unverified', 0)} unverified"
        )
        for path in flagged:
            self._say(f"  flagged: {path}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_progress.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/progress.py tests/test_progress.py
git commit -m "feat: add Reporter.verify_summary for refresh outcomes"
```

---

### Task 5: `_extract(refresh=...)` + `--refresh` on `search` and `get`

**Files:**
- Modify: `src/vtextract/cli.py` (`_extract` ~lines 256-298; `build_parser` ~line 98; `split_and_group` ~line 135; `_run_search` ~line 249; `_run_get` ~lines 315-348)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py` (it imports `cli`, `httpx`, `json`, `pytest`, defines `_write_config`, `_get_handler`, `EXAMPLES`). First, a HEAD-capable get handler and tests:

```python
def _refresh_get_handler(request, *, item_calls=None, loris=None):
    """Like _get_handler, plus a HEAD branch for /loris/ image verification."""
    path = request.url.path
    if path.startswith("/loris/") and request.method == "HEAD":
        img = (EXAMPLES / "item" / "loris" / "response.jpg").read_bytes()
        return httpx.Response(200, headers={"content-length": str(len(img))})
    if path.startswith("/loris/") and loris is not None:
        loris.append(path)
    if path == "/rest/isadg-identity-statements/474234" and item_calls is not None:
        item_calls.append(path)
    return _get_handler(request)


def test_get_refresh_reprocesses_completed_resource(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, item_calls=item_calls)),
    )
    # --context-pages 0: these tests don't mock the volume manifest, so no context fetch.
    base = ["get", "474234", "--out", str(tmp_path), "--config", str(config),
            "--context-pages", "0"]
    assert cli.run(base) == 0
    item_calls.clear()
    # without --refresh it would be skipped; with --refresh the detail is re-fetched
    assert cli.run(base + ["--refresh"]) == 0
    assert item_calls == ["/rest/isadg-identity-statements/474234"]


def test_get_refresh_verifies_image_with_head_not_get(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    loris: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, loris=loris)),
    )
    base = ["get", "474234", "--out", str(tmp_path), "--config", str(config),
            "--context-pages", "0"]
    assert cli.run(base) == 0
    loris.clear()  # GET-only list (HEAD requests are not appended)
    assert cli.run(base + ["--refresh"]) == 0
    assert loris == []  # size matched on HEAD -> no image GET


def test_search_refresh_parses_as_global_flag():
    from vtextract.cli import build_parser, split_and_group
    globals_, criteria = split_and_group(["houston", "--refresh"], build_parser())
    assert "--refresh" in globals_
    assert build_parser().parse_args(globals_).refresh is True
    assert [f.keywords for f in criteria.filters] == [["houston"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "refresh" -v`
Expected: FAIL — `--refresh` is unrecognized (walker errors / `_extract` has no `refresh`).

- [ ] **Step 3: Implement — `_extract`**

In `src/vtextract/cli.py`, change `_extract`'s signature and body. Replace the signature line (~256):

```python
def _extract(client, archive, hits, *, search_id: str, context_pages: int,
             reporter=None, refresh: bool = False) -> tuple[int, int]:
```

Just after `root_manifest_cache: dict = {}` (~line 265), add the refresh accumulators:

```python
    verified: set[str] = set()
    vcounts: dict[str, int] = {}
    flagged: list[str] = []

    def _on_verify(outcome: str, path: str) -> None:
        vcounts[outcome] = vcounts.get(outcome, 0) + 1
        if outcome in ("mismatch", "unverified"):
            flagged.append(path)
```

Change the completeness short-circuit (~line 275) so it is skipped in refresh mode:

```python
                if (not refresh) and isadg_id is not None and archive.is_resource_complete(isadg_id):
                    reporter.skip(isadg_id)
                    continue
```

Pass the refresh args into `fetch_resource` (~line 281):

```python
                    record = fetch_resource(
                        client, archive, hit,
                        search_id=search_id,
                        context_pages=context_pages,
                        on_item_start=reporter.item_pages,
                        on_page=reporter.page_done,
                        refresh=refresh,
                        on_verify=_on_verify,
                        _root_manifest_cache=root_manifest_cache,
                        _verified_pages=verified,
                    )
```

After the loop, before `reporter.finish(...)` (~line 297), add the summary:

```python
    if refresh:
        reporter.verify_summary(vcounts, flagged)
    reporter.finish(completed, failed)
    return completed, failed
```

- [ ] **Step 4: Implement — `--refresh` on `search`**

In `build_parser` (after the `--page-size` argument, ~line 105), add:

```python
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch metadata and HEAD-verify images for matched resources, "
        "even if already archived.",
    )
```

In `split_and_group`, define a bool-flags set near the other flag sets (just above the function, after line ~49) and route it. Add:

```python
# Zero-arg boolean global flags handled by argparse.
_BOOL_FLAGS = {"--refresh"}
```

Then change the first branch of the walker loop (~line 135) from:

```python
        if tok in ("--help", "-h") or tok in _SORT_FLAGS:
```
to:
```python
        if tok in ("--help", "-h") or tok in _SORT_FLAGS or tok in _BOOL_FLAGS:
```

In `_run_search`, pass `refresh` into `_extract` (~line 249):

```python
    completed, failed = _extract(
        client, archive, hits, search_id=search_id,
        context_pages=args.context_pages, reporter=reporter, refresh=args.refresh,
    )
```

- [ ] **Step 5: Implement — `--refresh` on `get`**

In `_run_get`'s parser (after `--context-pages`, ~line 318), add:

```python
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch metadata and HEAD-verify images for the given resources, "
        "even if already archived.",
    )
```

And pass it into `_extract` (~line 345):

```python
    completed, failed = _extract(
        client, archive, hits, search_id="get",
        context_pages=args.context_pages, reporter=reporter, refresh=args.refresh,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (including the pre-existing `test_get_twice_skips_completed_resource` and `test_run_twice_skips_completed_resource`, which do not pass `--refresh`).

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/cli.py tests/test_cli.py
git commit -m "feat: --refresh on search and get re-fetches and verifies archived items"
```

---

### Task 6: `refresh` subcommand

**Files:**
- Modify: `src/vtextract/cli.py` (add `_stdin_is_tty`, `_prompt_yes_no`, `_run_refresh`; register in `run`; update `_USAGE`)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def _seed_one_item(tmp_path, monkeypatch):
    """Archive item 474234 so the refresh command has something to enumerate."""
    config = _write_config(tmp_path)
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _get_handler(r)),
    )
    assert cli.run(["get", "474234", "--out", str(tmp_path), "--config", str(config),
                    "--context-pages", "0"]) == 0
    return config


def test_refresh_with_yes_reprocesses_all_items(tmp_path, monkeypatch):
    config = _seed_one_item(tmp_path, monkeypatch)
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, item_calls=item_calls)),
    )
    code = cli.run(["refresh", "--yes", "--out", str(tmp_path), "--config", str(config),
                    "--context-pages", "0"])
    assert code == 0
    assert item_calls == ["/rest/isadg-identity-statements/474234"]  # re-fetched


def test_refresh_declined_at_prompt_does_nothing(tmp_path, monkeypatch):
    config = _seed_one_item(tmp_path, monkeypatch)
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, item_calls=item_calls)),
    )
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli, "_prompt_yes_no", lambda *_a, **_k: False)
    code = cli.run(["refresh", "--out", str(tmp_path), "--config", str(config)])
    assert code == 0
    assert item_calls == []  # declined -> no requests


def test_refresh_non_tty_without_yes_aborts(tmp_path, monkeypatch, capsys):
    config = _seed_one_item(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
    code = cli.run(["refresh", "--out", str(tmp_path), "--config", str(config)])
    assert code == 2
    assert "--yes" in capsys.readouterr().err


def test_refresh_empty_archive_reports_and_exits_zero(tmp_path, monkeypatch, capsys):
    config = _write_config(tmp_path)
    (tmp_path / "items").mkdir()  # archive dir exists but has no items
    code = cli.run(["refresh", "--yes", "--out", str(tmp_path), "--config", str(config)])
    assert code == 0
    assert "no items" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "refresh_with_yes or declined or non_tty or empty_archive" -v`
Expected: FAIL — `unknown command: refresh` / missing `_stdin_is_tty`.

- [ ] **Step 3: Implement — confirmation helpers**

In `src/vtextract/cli.py`, add two module-level helpers (place them just above `_run_refresh`, which you add next):

```python
def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _prompt_yes_no(message: str) -> bool:
    try:
        return input(message).strip().lower() in ("y", "yes")
    except EOFError:
        return False
```

- [ ] **Step 4: Implement — `_run_refresh`**

Add this function (e.g. after `_run_get`, ~line 349):

```python
def _run_refresh(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="vtextract refresh",
        description="Re-fetch metadata and HEAD-verify images for every archived item.",
    )
    parser.add_argument(
        "--out", help="Archive directory (defaults to the config file's archive)."
    )
    parser.add_argument("--config", help="Config file path (default ~/.vt/vt.toml).")
    parser.add_argument(
        "--context-pages", type=_nonneg_int, default=1,
        help="Neighbouring physical pages to also consider per page (default 1).",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args(argv)

    config = load_config(Path(args.config) if args.config else None)
    if config.auth_header is None:
        print("No credentials configured. Run `vtextract auth`.", file=sys.stderr)
        return 2

    archive = Archive(args.out if args.out else config.archive)
    items_dir = archive.root / "items"
    hits = [
        {"isadgID": int(meta.parent.name)}
        for meta in sorted(items_dir.glob("*/metadata.json"))
        if meta.parent.name.isdigit()
    ]
    if not hits:
        print(f"no items to refresh in {archive.root}", file=sys.stderr)
        return 0

    if not args.yes:
        if not _stdin_is_tty():
            print(
                "refusing to run refresh without confirmation; re-run with --yes",
                file=sys.stderr,
            )
            return 2
        if not _prompt_yes_no(
            f"Refresh {len(hits)} item(s) in {archive.root}? This re-fetches "
            "metadata and HEAD-verifies every image against the server. [y/N] "
        ):
            print("aborted.", file=sys.stderr)
            return 0

    client = Client(
        base_url=config.base_url,
        auth_header=config.auth_header,
        user_agent=config.user_agent,
        transport=_make_transport(),
        delay=config.delay,
        max_retries=config.max_retries,
    )
    reporter = Reporter()
    reporter.set_total(len(hits), noun="items")
    completed, failed = _extract(
        client, archive, hits, search_id="refresh",
        context_pages=args.context_pages, reporter=reporter, refresh=True,
    )
    return 1 if failed else 0
```

- [ ] **Step 5: Implement — register the command + usage**

In `run` (~line 184), add the dispatch branch after the `auth` branch:

```python
    if command == "refresh":
        return _run_refresh(rest)
```

In `_USAGE` (~line 163), add a line under the commands list (after the `auth` line):

```python
  refresh  re-fetch metadata and verify images for the whole archive
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/cli.py tests/test_cli.py
git commit -m "feat: add vtextract refresh command with confirmation gate"
```

---

### Task 7: Docs + full-suite verification

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest`
Expected: PASS (all tests). If anything fails, STOP and fix before continuing.

- [ ] **Step 2: Update `README.md`**

Read the `get` / search usage section first to match style, then document the new surface. Add to the usage section:

```markdown
# re-fetch metadata + verify image sizes for already-archived resources
vtextract search --refresh houston            # scoped to search results
vtextract get --refresh TNA-SP-63-356         # scoped to given resources
vtextract refresh                             # the whole archive (asks to confirm; -y to skip)
```

And a short prose paragraph:

```markdown
`refresh` re-fetches each item's metadata (detail, manifest, `volume.json`) and
issues a `HEAD` for every referenced image, comparing the server's
`Content-Length` to the file on disk. Mismatched or missing images are
re-downloaded; images whose size cannot be verified are reported as
"unverified". The full-archive `refresh` asks for confirmation first (use
`-y/--yes` to skip); `--refresh` on `search`/`get` does the same for just those
resources.
```

- [ ] **Step 3: Update `CLAUDE.md`**

In the "Running things" section, extend the CLI bullet that documents `search`/`get` to mention refresh. Read the bullet first, then add:

```markdown
  A `refresh` command (and `--refresh` on `search`/`get`) re-fetches metadata for
  already-archived resources and HEAD-verifies image sizes against disk,
  re-downloading mismatches; the full-archive `refresh` confirms first (`-y` to skip).
```

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document refresh command and --refresh flag"
```

---

## Notes for the implementer

- **Run order matters:** Tasks 1→7 are sequential; later tasks call names defined earlier (`client.head`, `archive.page_size`, `fetch_resource(refresh=...)`, `Reporter.verify_summary`, `_extract(refresh=...)`, `_stdin_is_tty`/`_prompt_yes_no`).
- **No network, ever:** every test uses `httpx.MockTransport` or committed fixtures. HEAD requests are distinguished in handlers via `request.method == "HEAD"`.
- **The verify-or-redownload outcomes** are exactly `"ok" | "mismatch" | "missing" | "unverified"`; `_extract`'s `_on_verify` and `Reporter.verify_summary` must agree on these keys.
- **`refresh` reuses `_extract`** (one shared client, rate-limiter, root-manifest cache, and verified-set) rather than shelling out per item — semantically `get --refresh <every id>` in one process.
- **Testability seams:** `_make_transport` (HTTP), `_stdin_is_tty` and `_prompt_yes_no` (confirmation) are all module-level so tests monkeypatch them.
