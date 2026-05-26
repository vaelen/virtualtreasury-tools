# Virtual Treasury Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A resumable Python CLI that runs searches against virtualtreasury.ie and downloads every matching resource's full-resolution images, metadata, and transcriptions into a local archive, storing physical pages once per volume and sharing them across resources.

**Architecture:** Layered package — `client` (HTTP/auth/retry/rate-limit), `search` (doc_search body + pagination), `schema` (pure parsing of records, IIIF manifests, annotation lists), `archive` (shared per-volume page store + resource records + resume state), `fetcher` (per-resource orchestration), `cli` (wire-up). Pages are keyed by their Loris image identifier and grouped under `pages/{rootID}/`; resources under `items/{isadgID}/` reference them.

**Tech Stack:** Python 3.11+, `httpx` (HTTP, with `MockTransport` for tests), `pytest`. Standard library `json`, `pathlib`, `hashlib`, `base64`, `urllib.parse`.

**Reference:** Design spec at `docs/superpowers/specs/2026-05-26-virtualtreasury-extractor-design.md`. Captured API samples at `docs/examples/` (`doc-search/`, `item/<call>/`).

---

## File Structure

```
pyproject.toml                 # package metadata, deps, pytest config
src/vtextract/
  __init__.py
  config.py                    # Config dataclass + load_config() from env
  models.py                    # Page, PageRef, Record dataclasses
  client.py                    # Client: get_json/post_json/get_bytes, auth, retry, rate-limit
  search.py                    # parse_search_url, build_body, iter_results
  schema.py                    # pure parsers: records, manifests, annotation lists, context selection
  archive.py                   # Archive: page store, resource records, _state.json
  fetcher.py                   # fetch_resource orchestration
  cli.py                       # argparse main()
tests/
  conftest.py                  # fixture loaders pointing at docs/examples
  test_config.py
  test_client.py
  test_search.py
  test_schema.py
  test_archive.py
  test_fetcher.py
  test_cli.py
```

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/vtextract/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_scaffold.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scaffold.py`:
```python
def test_package_imports():
    import vtextract
    assert vtextract.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scaffold.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract'`

- [ ] **Step 3: Create the package and config files**

`pyproject.toml`:
```toml
[project]
name = "vtextract"
version = "0.1.0"
description = "Download resources from virtualtreasury.ie"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27"]

[project.scripts]
vtextract = "vtextract.cli:main"

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

`src/vtextract/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/conftest.py`:
```python
import json
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def load_example_json(*parts: str) -> dict:
    """Load a committed sample response, e.g. load_example_json('item', 'manifest')."""
    path = EXAMPLES.joinpath(*parts) / "response.json"
    return json.loads(path.read_text())


def load_example_bytes(*parts: str, name: str) -> bytes:
    return (EXAMPLES.joinpath(*parts) / name).read_bytes()


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES
```

- [ ] **Step 4: Install dev dependencies and run the test**

Run: `python -m pip install -e ".[dev]" && python -m pytest tests/test_scaffold.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/vtextract/__init__.py tests/conftest.py tests/test_scaffold.py
git commit -m "chore: scaffold vtextract package and pytest config"
```

---

## Task 2: Configuration loading

**Files:**
- Create: `src/vtextract/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import base64

import pytest

from vtextract.config import Config, load_config


def test_load_config_builds_basic_auth_header_from_token():
    cfg = load_config({"VT_AUTH": "dXNlcjpwYXNz"})  # base64 of "user:pass"
    assert cfg.auth_header == "Basic dXNlcjpwYXNz"
    assert cfg.base_url == "https://by2022-prod.adaptcentre.ie"
    assert cfg.index_db_name == "beyond_2022"


def test_load_config_builds_token_from_user_and_pass():
    cfg = load_config({"VT_USERNAME": "user", "VT_PASSWORD": "pass"})
    expected = base64.b64encode(b"user:pass").decode()
    assert cfg.auth_header == f"Basic {expected}"


def test_load_config_overrides_base_url_and_delay():
    cfg = load_config({"VT_AUTH": "x", "VT_BASE_URL": "https://example.test", "VT_DELAY": "0.5"})
    assert cfg.base_url == "https://example.test"
    assert cfg.delay == 0.5


def test_load_config_missing_credentials_raises():
    with pytest.raises(ValueError, match="VT_AUTH"):
        load_config({})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.config'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/config.py`:
```python
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://by2022-prod.adaptcentre.ie"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:151.0) "
    "Gecko/20100101 Firefox/151.0"
)
DEFAULT_INDEX_DB_NAME = "beyond_2022"


@dataclass
class Config:
    auth_header: str
    base_url: str = DEFAULT_BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    index_db_name: str = DEFAULT_INDEX_DB_NAME
    delay: float = 0.5
    max_retries: int = 3


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from environment variables.

    Credentials: set VT_AUTH to the base64 'user:pass' token, OR set both
    VT_USERNAME and VT_PASSWORD. Optional: VT_BASE_URL, VT_USER_AGENT,
    VT_INDEX_DB_NAME, VT_DELAY, VT_MAX_RETRIES.
    """
    env = os.environ if env is None else env

    token = env.get("VT_AUTH")
    if not token:
        username = env.get("VT_USERNAME")
        password = env.get("VT_PASSWORD")
        if username and password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
    if not token:
        raise ValueError(
            "Missing credentials: set VT_AUTH (base64 user:pass token) "
            "or VT_USERNAME and VT_PASSWORD."
        )

    return Config(
        auth_header=f"Basic {token}",
        base_url=env.get("VT_BASE_URL", DEFAULT_BASE_URL),
        user_agent=env.get("VT_USER_AGENT", DEFAULT_USER_AGENT),
        index_db_name=env.get("VT_INDEX_DB_NAME", DEFAULT_INDEX_DB_NAME),
        delay=float(env.get("VT_DELAY", "0.5")),
        max_retries=int(env.get("VT_MAX_RETRIES", "3")),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/config.py tests/test_config.py
git commit -m "feat: load config and auth header from environment"
```

---

## Task 3: HTTP client (auth, retry, rate-limit)

**Files:**
- Create: `src/vtextract/client.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_client.py`:
```python
import httpx
import pytest

from vtextract.client import Client


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return Client(
        base_url="https://api.test",
        auth_header="Basic xyz",
        user_agent="UA",
        transport=transport,
        delay=0.0,
        sleep_func=lambda _s: None,
        **kwargs,
    )


def test_get_json_sends_auth_and_parses_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["ua"] = request.headers.get("user-agent")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    assert client.get_json("/rest/thing/1") == {"ok": True}
    assert seen["auth"] == "Basic xyz"
    assert seen["ua"] == "UA"
    assert seen["url"] == "https://api.test/rest/thing/1"


def test_post_json_sends_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, content=b'{"totalDocs": 0}', headers={"content-type": "text/plain"})

    client = make_client(handler)
    result = client.post_json("/search", {"a": 1})
    assert result == {"totalDocs": 0}
    assert b'"a": 1' in seen["body"] or b'"a":1' in seen["body"]


def test_get_bytes_returns_raw_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xd8image")

    client = make_client(handler)
    assert client.get_bytes("https://api.test/loris/x/full/full/0/default.jpg") == b"\xff\xd8image"


def test_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=3)
    assert client.get_json("/x") == {"ok": True}
    assert calls["n"] == 3


def test_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = make_client(handler, max_retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("/x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.client'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/client.py`:
```python
from __future__ import annotations

import time
from collections.abc import Callable

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class Client:
    """Thin HTTP layer: auth header, polite rate-limit delay, retry/backoff.

    The single choke point for all backend requests.
    """

    def __init__(
        self,
        base_url: str,
        auth_header: str,
        *,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        delay: float = 0.5,
        max_retries: int = 3,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._delay = delay
        self._max_retries = max_retries
        self._sleep = sleep_func
        self._last_request = 0.0
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=60.0,
            headers={"Authorization": auth_header, "User-Agent": user_agent},
        )

    def _throttle(self) -> None:
        if self._delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._delay:
            self._sleep(self._delay - elapsed)
        self._last_request = time.monotonic()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._http.request(method, url, **kwargs)
                if response.status_code in RETRY_STATUS:
                    response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    self._sleep(2.0**attempt)
                    continue
                raise
        assert last_exc is not None  # unreachable
        raise last_exc

    def get_json(self, url: str) -> dict:
        return self._request("GET", url).json()

    def post_json(self, url: str, body: dict) -> dict:
        return self._request("POST", url, json=body).json()

    def get_bytes(self, url: str) -> bytes:
        return self._request("GET", url).content

    def close(self) -> None:
        self._http.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_client.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/client.py tests/test_client.py
git commit -m "feat: HTTP client with auth, retry and rate-limit"
```

---

## Task 4: Data models

**Files:**
- Create: `src/vtextract/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from vtextract.models import Page, PageRef, Record


def test_record_defaults_to_empty_pages():
    rec = Record(isadg_id=474234, reference_code="IMC 1954/RoD/1/1737/550", title="Will", search_hit={})
    assert rec.pages == []
    assert rec.detail is None


def test_page_holds_iiif_fields():
    page = Page(
        page_key="IMC_1954_RoD_1_Page_253.jpg",
        image_url="https://api/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg",
        annotation_list_urls=["https://api/iiif/v1/208925/list/197350"],
        root_id="208925",
        canvas_id="https://api/iiif/v1/208925/canvas/p235288",
        width=826,
        height=1368,
    )
    assert page.root_id == "208925"
    assert page.annotation_list_urls[0].endswith("197350")


def test_page_ref_records_role_and_path():
    ref = PageRef(
        page_key="x.jpg", root_id="208925", role="primary",
        path="pages/208925/x.jpg", canvas_label="lbl", width=1, height=2,
    )
    assert ref.role == "primary"
    assert ref.path == "pages/208925/x.jpg"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.models'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/models.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    """A physical page parsed from a IIIF canvas."""

    page_key: str                       # Loris identifier, e.g. "IMC_1954_RoD_1_Page_253.jpg"
    image_url: str                      # full-resolution image URL from the manifest
    annotation_list_urls: list[str]     # transcription annotation lists for this page
    root_id: str                        # volume id, from the canvas @id
    canvas_id: str
    canvas_label: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class PageRef:
    """A resource's reference to a stored page."""

    page_key: str
    root_id: str
    role: str                           # "primary" | "context"
    path: str                           # relative path "pages/{root_id}/{page_key}"
    canvas_label: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class Record:
    """A catalogued resource (isadgID)."""

    isadg_id: int
    reference_code: str
    title: str
    search_hit: dict
    detail: dict | None = None
    pages: list[PageRef] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/models.py tests/test_models.py
git commit -m "feat: add Page, PageRef and Record models"
```

---

## Task 5: Parse a search-results URL into query params

**Files:**
- Create: `src/vtextract/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search.py`:
```python
from vtextract.search import parse_search_url


def test_parse_search_url_extracts_query_params():
    url = (
        "https://virtualtreasury.ie/search-results?totalElementsInt=100&pageNumberInt=0"
        "&kwList=houston&kwOperList=ALL&searchContentDate_begin=1650-01-01"
        "&searchContentDate_end=1760-12-31&kwSearchFieldList=kwTranscription"
        "&resultSorting=relevance"
    )
    params = parse_search_url(url)
    assert params["kwList"] == "houston"
    assert params["kwOperList"] == "ALL"
    assert params["searchContentDate_begin"] == "1650-01-01"
    assert params["resultSorting"] == "relevance"
    # pagination params are managed by the tool, not carried from the URL
    assert "pageNumberInt" not in params
    assert "totalElementsInt" not in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.search'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/search.py`:
```python
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

# Pagination params are owned by the tool's pager, not taken from the user's URL.
_PAGINATION_KEYS = {"pageNumberInt", "totalElementsInt"}


def parse_search_url(url: str) -> dict[str, str]:
    """Extract doc_search query parameters from a /search-results URL.

    Multi-valued params collapse to their first value (the site uses single
    values for these keys).
    """
    query = parse_qs(urlparse(url).query, keep_blank_values=True)
    return {
        key: values[0]
        for key, values in query.items()
        if key not in _PAGINATION_KEYS and values
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_search.py::test_parse_search_url_extracts_query_params -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/search.py tests/test_search.py
git commit -m "feat: parse search-results URL into query params"
```

---

## Task 6: Build the doc_search request body

**Files:**
- Modify: `src/vtextract/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_search.py`)**

```python
from vtextract.search import build_body


def test_build_body_merges_index_name_and_pagination():
    params = {"kwList": "houston", "kwOperList": "ALL"}
    body = build_body(params, page_number=2, page_size=100, index_db_name="beyond_2022")
    assert body["indexDBName"] == "beyond_2022"
    assert body["kwList"] == "houston"
    assert body["kwOperList"] == "ALL"
    assert body["pageNumberInt"] == 2
    assert body["totalElementsInt"] == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_search.py::test_build_body_merges_index_name_and_pagination -v`
Expected: FAIL — `ImportError: cannot import name 'build_body'`

- [ ] **Step 3: Add the implementation (append to `src/vtextract/search.py`)**

```python
def build_body(
    params: dict[str, str],
    *,
    page_number: int,
    page_size: int,
    index_db_name: str,
) -> dict:
    """Construct the JSON body for POST /IR_REST_V2/webapi/doc_search."""
    return {
        "indexDBName": index_db_name,
        **params,
        "pageNumberInt": page_number,
        "totalElementsInt": page_size,
    }
```

Note: the call signature uses keyword-only args (`*`). Update the Step 1 test call to match if needed — it already passes them by keyword.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_search.py::test_build_body_merges_index_name_and_pagination -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/search.py tests/test_search.py
git commit -m "feat: build doc_search request body"
```

---

## Task 7: Paginate search results

**Files:**
- Modify: `src/vtextract/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_search.py`)**

```python
from vtextract.search import iter_results


class FakeSearchClient:
    """Stub Client.post_json that serves two pages of fake results."""

    def __init__(self):
        self.posted = []

    def post_json(self, url, body):
        self.posted.append(body)
        page = body["pageNumberInt"]
        if page == 0:
            return {
                "generalInfo": {"totalDocs": 3, "docNumberPerPage": 2, "currentPage": 1},
                "resultInfoList": [{"isadgID": 1}, {"isadgID": 2}],
            }
        return {
            "generalInfo": {"totalDocs": 3, "docNumberPerPage": 2, "currentPage": 2},
            "resultInfoList": [{"isadgID": 3}],
        }


def test_iter_results_yields_all_records_across_pages():
    client = FakeSearchClient()
    records = list(
        iter_results(
            client,
            {"kwList": "houston"},
            index_db_name="beyond_2022",
            page_size=2,
        )
    )
    assert [r["isadgID"] for r in records] == [1, 2, 3]
    assert client.posted[0]["pageNumberInt"] == 0
    assert client.posted[1]["pageNumberInt"] == 1
    assert len(client.posted) == 2  # stops once totalDocs reached
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_search.py::test_iter_results_yields_all_records_across_pages -v`
Expected: FAIL — `ImportError: cannot import name 'iter_results'`

- [ ] **Step 3: Add the implementation (append to `src/vtextract/search.py`)**

Add this import at the top of the file:
```python
from collections.abc import Iterator
```

Add the function:
```python
SEARCH_PATH = "/IR_REST_V2/webapi/doc_search"


def iter_results(
    client,
    params: dict[str, str],
    *,
    index_db_name: str,
    page_size: int = 100,
) -> Iterator[dict]:
    """Yield every resource record across all pages of a doc_search query."""
    page_number = 0
    seen = 0
    while True:
        body = build_body(
            params,
            page_number=page_number,
            page_size=page_size,
            index_db_name=index_db_name,
        )
        response = client.post_json(SEARCH_PATH, body)
        records = response.get("resultInfoList", [])
        total = response.get("generalInfo", {}).get("totalDocs", 0)
        for record in records:
            yield record
        seen += len(records)
        if not records or seen >= total:
            break
        page_number += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_search.py -v`
Expected: PASS (all search tests)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/search.py tests/test_search.py
git commit -m "feat: paginate doc_search results"
```

---

## Task 8: Extract the volume root id from a canvas @id

**Files:**
- Create: `src/vtextract/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

`tests/test_schema.py`:
```python
import pytest

from vtextract.schema import extract_root_id


def test_extract_root_id_from_canvas_id():
    canvas_id = "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288"
    assert extract_root_id(canvas_id) == "208925"


def test_extract_root_id_raises_when_absent():
    with pytest.raises(ValueError):
        extract_root_id("https://example.test/no/volume/here")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.schema'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/schema.py`:
```python
from __future__ import annotations

import re
from urllib.parse import unquote

from vtextract.models import Page, Record

_ROOT_ID_RE = re.compile(r"/iiif/v1/(\d+)/")


def extract_root_id(iiif_url: str) -> str:
    """Extract the volume manifest-root id embedded in a IIIF canvas/list @id."""
    match = _ROOT_ID_RE.search(iiif_url)
    if not match:
        raise ValueError(f"No IIIF root id found in URL: {iiif_url}")
    return match.group(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/schema.py tests/test_schema.py
git commit -m "feat: extract IIIF volume root id"
```

---

## Task 9: Parse a IIIF manifest into Page objects

**Files:**
- Modify: `src/vtextract/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_schema.py`)**

```python
from vtextract.schema import loris_filename, parse_manifest
from tests.conftest import load_example_json


def test_loris_filename_from_image_url():
    url = "https://by2022-prod.adaptcentre.ie/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg"
    assert loris_filename(url) == "IMC_1954_RoD_1_Page_253.jpg"


def test_parse_manifest_from_real_sample():
    manifest = load_example_json("item", "manifest")
    pages = parse_manifest(manifest)
    assert len(pages) == 1
    page = pages[0]
    assert page.page_key == "IMC_1954_RoD_1_Page_253.jpg"
    assert page.image_url.endswith("/full/full/0/default.jpg")
    assert page.root_id == "208925"
    assert page.canvas_id.endswith("/canvas/p235288")
    assert page.annotation_list_urls == [
        "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"
    ]
    assert page.width == 826
    assert page.height == 1368
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schema.py::test_parse_manifest_from_real_sample -v`
Expected: FAIL — `ImportError: cannot import name 'parse_manifest'`

- [ ] **Step 3: Add the implementation (append to `src/vtextract/schema.py`)**

```python
def loris_filename(image_url: str) -> str:
    """Pull the Loris page identifier out of a full image URL."""
    after = image_url.split("/loris/", 1)[1]
    return unquote(after.split("/", 1)[0])


def parse_manifest(manifest: dict) -> list[Page]:
    """Turn a IIIF Presentation manifest into ordered Page objects (one per canvas)."""
    pages: list[Page] = []
    for sequence in manifest.get("sequences", []):
        for canvas in sequence.get("canvases", []):
            pages.append(_parse_canvas(canvas))
    return pages


def _parse_canvas(canvas: dict) -> Page:
    canvas_id = canvas["@id"]
    images = canvas.get("images", [])
    resource = images[0]["resource"] if images else {}
    image_url = resource.get("@id", "")
    annotation_list_urls = [
        oc["@id"] for oc in canvas.get("otherContent", []) if "@id" in oc
    ]
    return Page(
        page_key=loris_filename(image_url) if image_url else "",
        image_url=image_url,
        annotation_list_urls=annotation_list_urls,
        root_id=extract_root_id(canvas_id),
        canvas_id=canvas_id,
        canvas_label=canvas.get("label"),
        width=canvas.get("width") or resource.get("width"),
        height=canvas.get("height") or resource.get("height"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/schema.py tests/test_schema.py
git commit -m "feat: parse IIIF manifest into Page objects"
```

---

## Task 10: Reconstruct transcription text from an annotation list

**Files:**
- Modify: `src/vtextract/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_schema.py`)**

```python
from vtextract.schema import reconstruct_text


def test_reconstruct_text_joins_chars_in_order():
    annotation_list = {
        "resources": [
            {"resource": {"@type": "cnt:ContentAsText", "chars": "line one"}},
            {"resource": {"@type": "cnt:ContentAsText", "chars": "line two"}},
        ]
    }
    assert reconstruct_text(annotation_list) == "line one\nline two"


def test_reconstruct_text_from_real_sample_starts_expected():
    sample = load_example_json("item", "list")
    text = reconstruct_text(sample)
    assert "REGISTRY OF DEEDS, DUBLIN" in text
    assert text.splitlines()[0] == "25"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schema.py::test_reconstruct_text_joins_chars_in_order -v`
Expected: FAIL — `ImportError: cannot import name 'reconstruct_text'`

- [ ] **Step 3: Add the implementation (append to `src/vtextract/schema.py`)**

```python
def reconstruct_text(annotation_list: dict) -> str:
    """Concatenate a page's text annotation fragments in document order."""
    chars: list[str] = []
    for annotation in annotation_list.get("resources", []):
        resource = annotation.get("resource", {})
        text = resource.get("chars")
        if text is not None:
            chars.append(text)
    return "\n".join(chars)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/schema.py tests/test_schema.py
git commit -m "feat: reconstruct transcription text from annotation list"
```

---

## Task 11: Select neighbouring context pages from a volume manifest

**Files:**
- Modify: `src/vtextract/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_schema.py`)**

```python
from vtextract.schema import neighbor_canvases


def _root_manifest():
    """Synthetic 4-page volume manifest for deterministic neighbour tests."""
    def canvas(n: int) -> dict:
        return {
            "@id": f"https://api/iiif/v1/208925/canvas/p{n}",
            "label": f"page {n}",
            "width": 10,
            "height": 20,
            "images": [
                {"resource": {"@id": f"https://api/loris/page_{n}.jpg/full/full/0/default.jpg"}}
            ],
            "otherContent": [{"@id": f"https://api/iiif/v1/208925/list/{n}"}],
        }

    return {"sequences": [{"canvases": [canvas(1), canvas(2), canvas(3), canvas(4)]}]}


def test_neighbor_canvases_returns_prev_and_next():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/p2", n=1)
    keys = [p.page_key for p in pages]
    assert keys == ["page_1.jpg", "page_3.jpg"]


def test_neighbor_canvases_clips_at_start_edge():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/p1", n=1)
    assert [p.page_key for p in pages] == ["page_2.jpg"]


def test_neighbor_canvases_clips_at_end_edge():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/p4", n=2)
    assert [p.page_key for p in pages] == ["page_2.jpg", "page_3.jpg"]


def test_neighbor_canvases_unknown_canvas_returns_empty():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/nope", n=1)
    assert pages == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schema.py::test_neighbor_canvases_returns_prev_and_next -v`
Expected: FAIL — `ImportError: cannot import name 'neighbor_canvases'`

- [ ] **Step 3: Add the implementation (append to `src/vtextract/schema.py`)**

```python
def neighbor_canvases(root_manifest: dict, canvas_id: str, n: int) -> list[Page]:
    """Return the n canvases before and after `canvas_id` in the volume sequence.

    The target canvas itself is excluded. Out-of-range neighbours are clipped.
    Returns [] if the canvas is not found or n <= 0.
    """
    if n <= 0:
        return []
    pages = parse_manifest(root_manifest)
    index = next((i for i, p in enumerate(pages) if p.canvas_id == canvas_id), None)
    if index is None:
        return []
    start = max(0, index - n)
    end = min(len(pages), index + n + 1)
    return [p for i, p in enumerate(pages[start:end], start=start) if i != index]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/schema.py tests/test_schema.py
git commit -m "feat: select context pages from volume manifest"
```

---

## Task 12: Normalize a record and extract volume info

**Files:**
- Modify: `src/vtextract/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_schema.py`)**

```python
from vtextract.schema import normalize_record, volume_info


def test_normalize_record_uses_search_hit_fields():
    hit = {
        "isadgID": 474234,
        "displayReferenceCode": "IMC 1954/RoD/1/1737/550",
        "displayTitle": "Will of MITCHELL, CALEB",
    }
    detail = {"id": 474234, "extentAndMedium": "1 will"}
    record = normalize_record(hit, detail)
    assert record.isadg_id == 474234
    assert record.reference_code == "IMC 1954/RoD/1/1737/550"
    assert record.title == "Will of MITCHELL, CALEB"
    assert record.search_hit is hit
    assert record.detail is detail
    assert record.pages == []


def test_volume_info_from_real_manifest():
    manifest = load_example_json("item", "manifest")
    info = volume_info(manifest)
    assert info["label"] == "Will of MITCHELL, CALEB, Dublin, carpenter, created 18 January 1724"
    assert info["reference_code"] == "IMC 1954/RoD/1/1737/550"
```

Note: the committed sample is the item manifest, whose label/ReferenceCode are
the item's own. The real volume (root) manifest has the same structure with the
volume's label; `volume_info` reads whatever manifest it is given.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schema.py::test_normalize_record_uses_search_hit_fields -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_record'`

- [ ] **Step 3: Add the implementation (append to `src/vtextract/schema.py`)**

```python
def normalize_record(search_hit: dict, detail: dict | None) -> Record:
    """Build a Record from a search hit and (optional) detail record."""
    return Record(
        isadg_id=int(search_hit["isadgID"]),
        reference_code=search_hit.get("displayReferenceCode", ""),
        title=search_hit.get("displayTitle", ""),
        search_hit=search_hit,
        detail=detail,
    )


def volume_info(manifest: dict) -> dict:
    """Extract a human-readable label and reference code from a IIIF manifest."""
    info = {"label": manifest.get("label"), "reference_code": None}
    for entry in manifest.get("metadata", []):
        if entry.get("label") == "ReferenceCode":
            info["reference_code"] = entry.get("value")
    return info
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS (all schema tests)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/schema.py tests/test_schema.py
git commit -m "feat: normalize records and extract volume info"
```

---

## Task 13: Archive — load and save resume state

**Files:**
- Create: `src/vtextract/archive.py`
- Test: `tests/test_archive.py`

- [ ] **Step 1: Write the failing test**

`tests/test_archive.py`:
```python
from vtextract.archive import Archive


def test_new_archive_has_empty_state(tmp_path):
    archive = Archive(tmp_path)
    assert archive.is_resource_complete(474234) is False
    assert archive.has_page("208925", "x.jpg") is False


def test_state_persists_across_instances(tmp_path):
    archive = Archive(tmp_path)
    archive.mark_resource_complete(474234, pages=[], search_id="houston")
    archive.save_state()

    reopened = Archive(tmp_path)
    assert reopened.is_resource_complete(474234) is True


def test_state_file_written_to_disk(tmp_path):
    archive = Archive(tmp_path)
    archive.mark_resource_failed(999, reason="boom")
    archive.save_state()
    assert (tmp_path / "_state.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_archive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.archive'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/archive.py`:
```python
from __future__ import annotations

import json
from pathlib import Path


class Archive:
    """Owns the on-disk archive: shared page store, resource records, resume state."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._state_path = self.root / "_state.json"
        if self._state_path.exists():
            self._state = json.loads(self._state_path.read_text())
        else:
            self._state = {"resources": {}, "pages": {}}

    # --- resume state ---

    def is_resource_complete(self, isadg_id: int) -> bool:
        entry = self._state["resources"].get(str(isadg_id))
        return bool(entry) and entry.get("status") == "complete"

    def mark_resource_complete(self, isadg_id: int, *, pages: list, search_id: str) -> None:
        entry = self._state["resources"].setdefault(str(isadg_id), {"searches": []})
        entry["status"] = "complete"
        entry["pages"] = pages
        if search_id and search_id not in entry["searches"]:
            entry["searches"].append(search_id)

    def mark_resource_failed(self, isadg_id: int, *, reason: str) -> None:
        entry = self._state["resources"].setdefault(str(isadg_id), {"searches": []})
        entry["status"] = "failed"
        entry["reason"] = reason

    def has_page(self, root_id: str, page_key: str) -> bool:
        return f"{root_id}/{page_key}" in self._state["pages"]

    def save_state(self) -> None:
        self._state_path.write_text(json.dumps(self._state, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_archive.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/archive.py tests/test_archive.py
git commit -m "feat: archive resume-state load/save"
```

---

## Task 14: Archive — shared per-volume page store

**Files:**
- Modify: `src/vtextract/archive.py`
- Test: `tests/test_archive.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_archive.py`)**

```python
import hashlib


def test_store_page_writes_files_and_registers(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(
        root_id="208925",
        page_key="p1.jpg",
        image_bytes=b"\xff\xd8jpegbytes",
        text="hello world",
        annotations={"resources": [{"resource": {"chars": "hello world"}}]},
    )
    base = tmp_path / "pages" / "208925"
    assert (base / "p1.jpg").read_bytes() == b"\xff\xd8jpegbytes"
    assert (base / "p1.jpg.txt").read_text() == "hello world"
    assert "hello world" in (base / "p1.jpg.json").read_text()
    assert archive.has_page("208925", "p1.jpg") is True


def test_store_page_records_checksum(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg", image_bytes=b"abc", text=None, annotations=None)
    expected = hashlib.sha256(b"abc").hexdigest()
    assert archive.page_checksum("208925", "p1.jpg") == expected


def test_store_page_without_text_skips_transcription_files(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg", image_bytes=b"abc", text=None, annotations=None)
    base = tmp_path / "pages" / "208925"
    assert (base / "p1.jpg").exists()
    assert not (base / "p1.jpg.txt").exists()
    assert not (base / "p1.jpg.json").exists()


def test_write_volume_info(tmp_path):
    archive = Archive(tmp_path)
    archive.write_volume_info("208925", {"label": "Vol 1", "reference_code": "IMC 1954/RoD/1"})
    import json as _json
    data = _json.loads((tmp_path / "pages" / "208925" / "volume.json").read_text())
    assert data["label"] == "Vol 1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_archive.py::test_store_page_writes_files_and_registers -v`
Expected: FAIL — `AttributeError: 'Archive' object has no attribute 'store_page'`

- [ ] **Step 3: Add the implementation (append methods to the `Archive` class in `src/vtextract/archive.py`)**

Add `import hashlib` at the top of the file, then add these methods to `Archive`:
```python
    # --- shared page store ---

    def _page_dir(self, root_id: str) -> Path:
        path = self.root / "pages" / root_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def page_relative_path(self, root_id: str, page_key: str) -> str:
        return f"pages/{root_id}/{page_key}"

    def page_checksum(self, root_id: str, page_key: str) -> str | None:
        entry = self._state["pages"].get(f"{root_id}/{page_key}")
        return entry["sha256"] if entry else None

    def store_page(
        self,
        *,
        root_id: str,
        page_key: str,
        image_bytes: bytes,
        text: str | None,
        annotations: dict | None,
    ) -> None:
        page_dir = self._page_dir(root_id)
        (page_dir / page_key).write_bytes(image_bytes)
        if text is not None:
            (page_dir / f"{page_key}.txt").write_text(text)
        if annotations is not None:
            (page_dir / f"{page_key}.json").write_text(json.dumps(annotations, indent=2))
        self._state["pages"][f"{root_id}/{page_key}"] = {
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "bytes": len(image_bytes),
        }

    def write_volume_info(self, root_id: str, info: dict) -> None:
        (self._page_dir(root_id) / "volume.json").write_text(json.dumps(info, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_archive.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/archive.py tests/test_archive.py
git commit -m "feat: shared per-volume page store with checksums"
```

---

## Task 15: Archive — write resource records

**Files:**
- Modify: `src/vtextract/archive.py`
- Test: `tests/test_archive.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_archive.py`)**

```python
import json as _json

from vtextract.models import PageRef, Record


def test_write_resource_writes_metadata_and_manifest(tmp_path):
    archive = Archive(tmp_path)
    record = Record(
        isadg_id=474234,
        reference_code="IMC 1954/RoD/1/1737/550",
        title="Will of MITCHELL, CALEB",
        search_hit={"isadgID": 474234},
        detail={"id": 474234},
        pages=[PageRef(page_key="p1.jpg", root_id="208925", role="primary",
                       path="pages/208925/p1.jpg", canvas_label="lbl", width=826, height=1368)],
    )
    archive.write_resource(record, manifest={"@type": "sc:Manifest"})

    item_dir = tmp_path / "items" / "474234"
    metadata = _json.loads((item_dir / "metadata.json").read_text())
    assert metadata["isadgID"] == 474234
    assert metadata["referenceCode"] == "IMC 1954/RoD/1/1737/550"
    assert metadata["searchHit"] == {"isadgID": 474234}
    assert metadata["detail"] == {"id": 474234}
    assert metadata["pages"][0]["page_key"] == "p1.jpg"
    assert metadata["pages"][0]["role"] == "primary"

    manifest = _json.loads((item_dir / "manifest.json").read_text())
    assert manifest["@type"] == "sc:Manifest"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_archive.py::test_write_resource_writes_metadata_and_manifest -v`
Expected: FAIL — `AttributeError: 'Archive' object has no attribute 'write_resource'`

- [ ] **Step 3: Add the implementation (append method to `Archive`)**

Add `from dataclasses import asdict` to the imports, then add to `Archive`:
```python
    # --- resource records ---

    def write_resource(self, record: Record, *, manifest: dict | None) -> None:
        item_dir = self.root / "items" / str(record.isadg_id)
        item_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "isadgID": record.isadg_id,
            "referenceCode": record.reference_code,
            "title": record.title,
            "pages": [asdict(ref) for ref in record.pages],
            "searchHit": record.search_hit,
            "detail": record.detail,
        }
        (item_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        if manifest is not None:
            (item_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_archive.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/archive.py tests/test_archive.py
git commit -m "feat: write resource metadata and manifest records"
```

---

## Task 16: Fetcher — orchestrate per-resource retrieval

**Files:**
- Create: `src/vtextract/fetcher.py`
- Test: `tests/test_fetcher.py`

This task wires `client` + `schema` + `archive` into the full per-resource
flow, and is tested as an integration against the committed fixtures using
`httpx.MockTransport`. Context-page fetching is verified separately with a
synthetic root manifest.

- [ ] **Step 1: Write the failing test**

`tests/test_fetcher.py`:
```python
import json
from pathlib import Path

import httpx

from vtextract.client import Client
from vtextract.fetcher import fetch_resource

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def _item_json(call: str) -> bytes:
    return (EXAMPLES / "item" / call / "response.json").read_bytes()


def _item_image() -> bytes:
    return (EXAMPLES / "item" / "loris" / "response.jpg").read_bytes()


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/rest/isadg-identity-statements/474234":
        return httpx.Response(200, content=_item_json("isadg-identity-statements"))
    if path == "/iiif/v1/474234/manifest":
        return httpx.Response(200, content=_item_json("manifest"))
    if path == "/iiif/v1/208925/list/197350":
        return httpx.Response(200, content=_item_json("list"))
    if path == "/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg":
        return httpx.Response(200, content=_item_image())
    return httpx.Response(404, text=f"unexpected {path}")


def _client() -> Client:
    return Client(
        base_url="https://by2022-prod.adaptcentre.ie",
        auth_header="Basic x",
        user_agent="UA",
        transport=httpx.MockTransport(_handler),
        delay=0.0,
        sleep_func=lambda _s: None,
    )


def test_fetch_resource_downloads_page_metadata_and_transcription(tmp_path):
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    search_hit = {
        "isadgID": 474234,
        "displayReferenceCode": "IMC 1954/RoD/1/1737/550",
        "displayTitle": "Will of MITCHELL, CALEB",
    }
    record = fetch_resource(
        _client(), archive, search_hit, search_id="houston", context_pages=0
    )

    # resource record written
    metadata = json.loads((tmp_path / "items" / "474234" / "metadata.json").read_text())
    assert metadata["referenceCode"] == "IMC 1954/RoD/1/1737/550"
    assert len(metadata["pages"]) == 1
    assert metadata["pages"][0]["role"] == "primary"
    assert metadata["pages"][0]["path"] == "pages/208925/IMC_1954_RoD_1_Page_253.jpg"

    # page stored once under its volume
    page_dir = tmp_path / "pages" / "208925"
    assert (page_dir / "IMC_1954_RoD_1_Page_253.jpg").exists()
    assert "REGISTRY OF DEEDS, DUBLIN" in (page_dir / "IMC_1954_RoD_1_Page_253.jpg.txt").read_text()
    assert archive.is_resource_complete(474234) is True
    assert record.isadg_id == 474234


def test_fetch_resource_skips_already_stored_page(tmp_path):
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    search_hit = {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}

    calls = {"loris": 0}
    base_handler = _handler

    def counting_handler(request: httpx.Request) -> httpx.Response:
        if "/loris/" in request.url.path:
            calls["loris"] += 1
        return base_handler(request)

    def client():
        return Client(
            base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
            user_agent="UA", transport=httpx.MockTransport(counting_handler),
            delay=0.0, sleep_func=lambda _s: None,
        )

    fetch_resource(client(), archive, search_hit, search_id="s1", context_pages=0)
    fetch_resource(client(), archive, dict(search_hit, isadgID=474234), search_id="s2", context_pages=0)
    # second call must reuse the stored page, not re-download it
    assert calls["loris"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.fetcher'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/fetcher.py`:
```python
from __future__ import annotations

from vtextract.archive import Archive
from vtextract.client import Client
from vtextract.models import Page, PageRef, Record
from vtextract.schema import (
    neighbor_canvases,
    normalize_record,
    parse_manifest,
    reconstruct_text,
    volume_info,
)


def fetch_resource(
    client: Client,
    archive: Archive,
    search_hit: dict,
    *,
    search_id: str,
    context_pages: int = 1,
    _root_manifest_cache: dict | None = None,
) -> Record:
    """Fetch one resource: detail metadata, manifest, images, transcriptions.

    Stores each physical page once in the shared per-volume page store and
    writes the resource record referencing its primary and context pages.
    """
    isadg_id = int(search_hit["isadgID"])
    cache = _root_manifest_cache if _root_manifest_cache is not None else {}

    try:
        detail = client.get_json(f"/rest/isadg-identity-statements/{isadg_id}")
        manifest = client.get_json(f"/iiif/v1/{isadg_id}/manifest")
        primary_pages = parse_manifest(manifest)

        page_refs: list[PageRef] = []
        for page in primary_pages:
            _ensure_page(client, archive, page, role="primary", refs=page_refs)
            for ctx in _context_for(client, cache, page, context_pages):
                _ensure_page(client, archive, ctx, role="context", refs=page_refs)

        record = normalize_record(search_hit, detail)
        record.pages = page_refs
        archive.write_resource(record, manifest=manifest)
        archive.mark_resource_complete(isadg_id, pages=[r.page_key for r in page_refs], search_id=search_id)
        archive.save_state()
        return record
    except Exception as exc:  # noqa: BLE001 - record failure and re-raise for the caller to log
        archive.mark_resource_failed(isadg_id, reason=repr(exc))
        archive.save_state()
        raise


def _context_for(client: Client, cache: dict, page: Page, context_pages: int) -> list[Page]:
    if context_pages <= 0:
        return []
    if page.root_id not in cache:
        root_manifest = client.get_json(f"/iiif/v1/{page.root_id}/manifest")
        cache[page.root_id] = root_manifest
    return neighbor_canvases(cache[page.root_id], page.canvas_id, context_pages)


def _ensure_page(
    client: Client,
    archive: Archive,
    page: Page,
    *,
    role: str,
    refs: list[PageRef],
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

    if archive.has_page(page.root_id, page.page_key):
        return

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/fetcher.py tests/test_fetcher.py
git commit -m "feat: per-resource fetch orchestration with shared page store"
```

---

## Task 17: Fetcher — context pages and volume.json

**Files:**
- Modify: `src/vtextract/fetcher.py`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_fetcher.py`)**

```python
def test_fetch_resource_pulls_context_pages_and_writes_volume_info(tmp_path):
    from vtextract.archive import Archive

    # Root manifest with three pages; the item's page is the middle one (p235288).
    root_manifest = {
        "label": "Registry of Deeds... abstracts of wills, volume 1: 1708-45",
        "metadata": [{"label": "ReferenceCode", "value": "IMC 1954/RoD/1"}],
        "sequences": [{"canvases": [
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/before",
             "label": "before", "width": 1, "height": 1,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/before.jpg/full/full/0/default.jpg"}}],
             "otherContent": []},
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288",
             "label": "IMC 1954/RoD/1/1737/550", "width": 826, "height": 1368,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg"}}],
             "otherContent": [{"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"}]},
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/after",
             "label": "after", "width": 1, "height": 1,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/after.jpg/full/full/0/default.jpg"}}],
             "otherContent": []},
        ]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/iiif/v1/208925/manifest":
            return httpx.Response(200, json=root_manifest)
        if path.startswith("/loris/"):
            return httpx.Response(200, content=b"\xff\xd8img")
        return _handler(request)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    search_hit = {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}

    record = fetch_resource(client, archive, search_hit, search_id="s", context_pages=1)

    roles = {r.page_key: r.role for r in record.pages}
    assert roles["IMC_1954_RoD_1_Page_253.jpg"] == "primary"
    assert roles["before.jpg"] == "context"
    assert roles["after.jpg"] == "context"
    # context pages were stored
    assert (tmp_path / "pages" / "208925" / "before.jpg").exists()
    assert (tmp_path / "pages" / "208925" / "after.jpg").exists()
    # volume.json written from the root manifest
    import json as _json
    vol = _json.loads((tmp_path / "pages" / "208925" / "volume.json").read_text())
    assert vol["reference_code"] == "IMC 1954/RoD/1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher.py::test_fetch_resource_pulls_context_pages_and_writes_volume_info -v`
Expected: FAIL — `volume.json` not written (assertion error on the final read), because the current implementation never writes volume info.

- [ ] **Step 3: Update `_context_for` to write volume.json when it fetches a root manifest**

In `src/vtextract/fetcher.py`, replace the `_context_for` function with:
```python
def _context_for(client: Client, cache: dict, archive: Archive, page: Page, context_pages: int) -> list[Page]:
    if context_pages <= 0:
        return []
    if page.root_id not in cache:
        root_manifest = client.get_json(f"/iiif/v1/{page.root_id}/manifest")
        cache[page.root_id] = root_manifest
        archive.write_volume_info(page.root_id, volume_info(root_manifest))
    return neighbor_canvases(cache[page.root_id], page.canvas_id, context_pages)
```

And update its single call site inside `fetch_resource` to pass `archive`:
```python
            for ctx in _context_for(client, cache, archive, page, context_pages):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fetcher.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/fetcher.py tests/test_fetcher.py
git commit -m "feat: fetch context pages and write volume.json"
```

---

## Task 18: CLI

**Files:**
- Create: `src/vtextract/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import httpx

from vtextract import cli


def test_run_archives_results_end_to_end(tmp_path, monkeypatch):
    # Stub the network: one search page with one result, then the item fan-out.
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "IMC 1954/RoD/1/1737/550",
             "displayTitle": "Will of MITCHELL, CALEB"}
        ],
    }

    from pathlib import Path
    examples = Path(__file__).resolve().parent.parent / "docs" / "examples"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/IR_REST_V2/webapi/doc_search":
            return httpx.Response(200, json=search_response)
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=(examples / "item" / "isadg-identity-statements" / "response.json").read_bytes())
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=(examples / "item" / "manifest" / "response.json").read_bytes())
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=(examples / "item" / "list" / "response.json").read_bytes())
        if path.startswith("/loris/"):
            return httpx.Response(200, content=(examples / "item" / "loris" / "response.jpg").read_bytes())
        return httpx.Response(404, text=path)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))

    exit_code = cli.run(
        ["https://virtualtreasury.ie/search-results?kwList=houston",
         "--out", str(tmp_path), "--context-pages", "0"],
        env={"VT_AUTH": "x", "VT_DELAY": "0"},
    )
    assert exit_code == 0
    assert (tmp_path / "items" / "474234" / "metadata.json").exists()
    assert (tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.cli'`

- [ ] **Step 3: Write the implementation**

`src/vtextract/cli.py`:
```python
from __future__ import annotations

import argparse
import sys

import httpx

from vtextract.archive import Archive
from vtextract.client import Client
from vtextract.config import load_config
from vtextract.fetcher import fetch_resource
from vtextract.search import iter_results, parse_search_url


def _make_transport() -> httpx.BaseTransport | None:
    """Seam for tests to inject a MockTransport. Returns None in production."""
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtextract",
        description="Download resources matching a virtualtreasury.ie search.",
    )
    parser.add_argument("search_url", help="A /search-results URL to archive.")
    parser.add_argument("--out", required=True, help="Output archive directory.")
    parser.add_argument(
        "--context-pages", type=int, default=1,
        help="Neighbouring physical pages to also fetch per page (default 1).",
    )
    parser.add_argument(
        "--page-size", type=int, default=100,
        help="doc_search page size (default 100).",
    )
    return parser


def run(argv: list[str], *, env: dict[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(env)

    client = Client(
        base_url=config.base_url,
        auth_header=config.auth_header,
        user_agent=config.user_agent,
        transport=_make_transport(),
        delay=config.delay,
        max_retries=config.max_retries,
    )
    archive = Archive(args.out)
    params = parse_search_url(args.search_url)
    search_id = args.search_url
    root_manifest_cache: dict = {}

    completed = 0
    failed = 0
    try:
        for hit in iter_results(client, params, index_db_name=config.index_db_name, page_size=args.page_size):
            isadg_id = int(hit["isadgID"])
            if archive.is_resource_complete(isadg_id):
                print(f"skip {isadg_id} (already complete)")
                continue
            try:
                fetch_resource(
                    client, archive, hit,
                    search_id=search_id,
                    context_pages=args.context_pages,
                    _root_manifest_cache=root_manifest_cache,
                )
                completed += 1
                print(f"done {isadg_id}")
            except Exception as exc:  # noqa: BLE001 - one bad item must not stop the run
                failed += 1
                print(f"FAILED {isadg_id}: {exc!r}", file=sys.stderr)
    finally:
        client.close()

    print(f"finished: {completed} archived, {failed} failed")
    return 0


def main() -> None:
    sys.exit(run(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS (all tests green)

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/cli.py tests/test_cli.py
git commit -m "feat: CLI wiring search -> fetch -> archive"
```

---

## Task 19: README and usage docs

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

`README.md`:
```markdown
# vtextract

Download resources from [virtualtreasury.ie](https://virtualtreasury.ie) — full
-resolution images, metadata, and transcriptions — into a resumable local
archive. See the design spec in
`docs/superpowers/specs/2026-05-26-virtualtreasury-extractor-design.md`.

## Install

```bash
python -m pip install -e ".[dev]"
```

## Credentials

The backend requires an HTTP Basic credential (the same one the public site's
JavaScript sends). Provide it via the environment — it is never stored in the
repo:

```bash
export VT_AUTH="<base64 user:pass token>"
# or
export VT_USERNAME="..." VT_PASSWORD="..."
```

Optional: `VT_BASE_URL`, `VT_DELAY` (seconds between requests, default 0.5),
`VT_MAX_RETRIES`.

## Usage

```bash
vtextract "https://virtualtreasury.ie/search-results?kwList=houston&kwOperList=ALL&\
searchContentDate_begin=1650-01-01&searchContentDate_end=1760-12-31&\
kwSearchFieldList=kwTranscription&resultSorting=relevance" \
  --out ./archive --context-pages 1
```

Re-running the same (or an overlapping) search resumes: completed resources and
already-downloaded pages are skipped.

## Archive layout

```
archive/
  _state.json
  pages/<volumeId>/<pageFile>.jpg(.txt/.json)   # shared, one copy per physical page
  items/<isadgID>/metadata.json, manifest.json  # resources referencing their pages
```

## Tests

```bash
python -m pytest
```

Tests run entirely against committed sample responses in `docs/examples/`; they
never contact the live site or use the real credential.
```

- [ ] **Step 2: Verify the suite still passes**

Run: `python -m pytest -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with install, credentials and usage"
```

---

## Final verification

- [ ] Run the full test suite: `python -m pytest -v` — all green.
- [ ] Confirm the package entry point exists: `vtextract --help` prints usage.
- [ ] Manual smoke test (optional, hits the live site, requires real `VT_AUTH`):
  `vtextract "<a real search-results URL>" --out /tmp/vt-smoke --context-pages 0`
  then inspect `/tmp/vt-smoke/items/*/metadata.json` and `/tmp/vt-smoke/pages/*/`.
