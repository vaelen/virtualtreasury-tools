# Volume Page Ordering + `vtindex page` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record an ordered page list + descriptive `title` in each volume's `volume.json`, index page ordinals (also giving complete page coverage), and add a `vtindex page <root_id>/<page_key>` command that prints a page's previous / current / next neighbours with their file paths.

**Architecture:** `schema.volume_info` (pure) gains a `pages` list built from the existing `parse_manifest`, plus a `title` it receives as an argument; `fetcher._context_for` does the one I/O call to fetch the root's descriptive title and passes it in. The index `page` table gains `ordinal`/`label` columns and the `volume` table gains `title`; volume indexing becomes authoritative for page existence + ordering while transcription indexing keeps owning `has_text`, neither clobbering the other. A new `vtindex page` command composes prev/current/next from `db` primitives.

**Tech Stack:** Python 3, `uv`, `pytest`, `httpx.MockTransport`, SQLite + FTS5, `rich`. Spec: `docs/superpowers/specs/2026-05-27-volume-page-ordering-design.md`.

**Conventions:** TDD (write failing test, see it fail, implement minimally, see it pass, commit). Tests run against committed fixtures only; never hit the network. Run tests with `uv run pytest`.

---

### Task 1: `schema.detail_title` + `volume_info` gains `pages` and `title`

**Files:**
- Modify: `src/vtextract/schema.py` (the `volume_info` function near line 111; add `detail_title`)
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_schema.py`. Note `volume_info` is already imported on line 104 (`from vtextract.schema import normalize_record, normalize_reference_code, volume_info`); extend that import line to also import `detail_title`:

```python
from vtextract.schema import (
    detail_title,
    normalize_record,
    normalize_reference_code,
    volume_info,
)
```

Then add these tests:

```python
def test_detail_title_from_real_detail():
    detail = load_example_json("item", "isadg-identity-statements")
    assert detail_title(detail) == "Will of MITCHELL, CALEB, Dublin, carpenter, created 18 January 1724"


def test_detail_title_empty_when_absent():
    assert detail_title({"id": 1}) == ""


def test_volume_info_includes_ordered_pages():
    manifest = load_example_json("item", "manifest")
    info = volume_info(manifest)
    assert info["pages"] == [
        {
            "page_key": "IMC_1954_RoD_1_Page_253.jpg",
            "label": "IMC 1954/RoD/1/1737/550",
            "canvas_id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288",
        }
    ]


def test_volume_info_title_defaults_none_and_passes_through():
    manifest = load_example_json("item", "manifest")
    assert volume_info(manifest)["title"] is None
    assert volume_info(manifest, title="A Volume")["title"] == "A Volume"


def test_volume_info_skips_canvas_without_image():
    manifest = {"sequences": [{"canvases": [
        {"@id": "https://api/iiif/v1/9/canvas/p1", "label": "ok",
         "images": [{"resource": {"@id": "https://api/loris/a.jpg/full/full/0/default.jpg"}}]},
        {"@id": "https://api/iiif/v1/9/canvas/p2", "label": "no image", "images": []},
    ]}]}
    keys = [p["page_key"] for p in volume_info(manifest)["pages"]]
    assert keys == ["a.jpg"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schema.py -k "detail_title or volume_info" -v`
Expected: FAIL — `ImportError: cannot import name 'detail_title'` (and the new `volume_info` assertions would fail on missing `pages`/`title` keys).

- [ ] **Step 3: Implement**

In `src/vtextract/schema.py`, replace the existing `volume_info` (currently lines 111–117) and add `detail_title`:

```python
def detail_title(detail: dict) -> str:
    """The descriptive title from an identity-statement detail object."""
    return (detail.get("preferredTitle") or {}).get("title") or ""


def volume_info(manifest: dict, *, title: str | None = None) -> dict:
    """Extract label, reference code, descriptive title, and ordered pages.

    `title` is the volume root's descriptive title, supplied by the caller (the
    manifest itself carries only the shelfmark). `pages` is one entry per canvas
    in sequence order; canvases without a parseable image are skipped.
    """
    info = {"label": manifest.get("label"), "reference_code": None, "title": title}
    for entry in manifest.get("metadata", []):
        if entry.get("label") == "ReferenceCode":
            info["reference_code"] = entry.get("value")
    info["pages"] = [
        {"page_key": page.page_key, "label": page.canvas_label, "canvas_id": page.canvas_id}
        for page in parse_manifest(manifest)
        if page.page_key
    ]
    return info
```

`parse_manifest` is already defined above in the same module (line 30), so no new import is needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py -v`
Expected: PASS (all schema tests, including the pre-existing `test_volume_info_from_real_manifest`).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/schema.py tests/test_schema.py
git commit -m "feat: volume_info emits ordered pages and accepts a title"
```

---

### Task 2: `fetcher` fetches the root's title into `volume.json`

**Files:**
- Modify: `src/vtextract/fetcher.py` (the import block lines 12–19; `_context_for` lines 98–105)
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write the failing tests**

The existing `test_fetch_resource_pulls_context_pages_and_writes_volume_info` (line 152) builds a `root_manifest` and asserts `vol["reference_code"]`. Extend its assertions (after the existing `assert vol["reference_code"] == "IMC 1954/RoD/1"`, near line 201) to cover the ordered pages and the graceful no-title fallback (the root id `208925`'s identity-statement is **not** mocked in that test's handler, so the title fetch fails and must degrade to `None`):

```python
    assert vol["title"] is None  # root detail 208925 is not mocked -> graceful fallback
    assert [p["page_key"] for p in vol["pages"]] == ["before.jpg", "IMC_1954_RoD_1_Page_253.jpg", "after.jpg"]
    assert vol["pages"][1]["label"] == "IMC 1954/RoD/1/1737/550"
```

Then add a new test that *does* mock the root identity-statement so the title is captured:

```python
def test_fetch_resource_writes_volume_title_from_root_detail(tmp_path):
    from vtextract.archive import Archive

    root_manifest = {
        "label": "TNA SP 63/356",
        "metadata": [{"label": "ReferenceCode", "value": "TNA SP 63/356"}],
        "sequences": [{"canvases": [
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288",
             "label": "IMC 1954/RoD/1/1737/550", "width": 826, "height": 1368,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg"}}],
             "otherContent": [{"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"}]},
        ]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/iiif/v1/208925/manifest":
            return httpx.Response(200, json=root_manifest)
        if path == "/rest/isadg-identity-statements/208925":
            # the volume root's own descriptive title
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path.startswith("/loris/"):
            return httpx.Response(200, content=b"\xff\xd8img")
        return _handler(request)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    fetch_resource(client, archive, {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"},
                   search_id="s", context_pages=1)

    vol = json.loads((tmp_path / "pages" / "208925" / "volume.json").read_text())
    assert vol["title"] == "Will of MITCHELL, CALEB, Dublin, carpenter, created 18 January 1724"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetcher.py -k volume -v`
Expected: FAIL — `volume.json` has no `title`/`pages` keys yet (`KeyError`), and the new test's title is never written.

- [ ] **Step 3: Implement**

In `src/vtextract/fetcher.py`, add `detail_title` to the schema import block (lines 12–19):

```python
from vtextract.schema import (
    detail_title,
    neighbor_canvases,
    normalize_record,
    normalize_reference_code,
    parse_manifest,
    reconstruct_text,
    volume_info,
)
```

Replace `_context_for` (lines 98–105) with:

```python
def _volume_title(client: Client, root_id: str) -> str | None:
    """Best-effort descriptive title for the volume root; None if unavailable."""
    try:
        detail = client.get_json(f"{IDENTITY_STATEMENT_PATH}{root_id}")
    except Exception:  # noqa: BLE001 - title is optional; never block the volume record
        return None
    return detail_title(detail) or None


def _context_for(client: Client, cache: dict, archive: Archive, page: Page, context_pages: int) -> list[Page]:
    if context_pages <= 0:
        return []
    if page.root_id not in cache:
        root_manifest = client.get_json(f"/iiif/v1/{page.root_id}/manifest")
        cache[page.root_id] = root_manifest
        title = _volume_title(client, page.root_id)
        archive.write_volume_info(page.root_id, volume_info(root_manifest, title=title))
    return neighbor_canvases(cache[page.root_id], page.canvas_id, context_pages)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: PASS (all fetcher tests).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/fetcher.py tests/test_fetcher.py
git commit -m "feat: write volume title and ordered pages into volume.json on fetch"
```

---

### Task 3: index models + `read_volume` return `title` and ordered pages (with fixtures)

**Files:**
- Modify: `src/vtextract/index/models.py` (`VolumeRow` line 39, `VolumeInfo` line 71; add `VolumePage`)
- Modify: `src/vtextract/index/reader.py` (`read_volume` line 68)
- Modify (fixtures): `tests/fixtures/archive/pages/volA/volume.json`, `tests/fixtures/archive/pages/volB/volume.json`
- Test: `tests/index/test_reader.py`

- [ ] **Step 1: Update the fixtures**

The reader tests parse these. Rewrite each to include `title` and an ordered `pages` list (matching the transcription files already in those dirs — `volA_p0.jpg`, `volA_p1.jpg`, `volB_p5.jpg`).

`tests/fixtures/archive/pages/volA/volume.json`:

```json
{
  "label": "Registry of Deeds Transcript Book 86",
  "reference_code": "IMC 1954/RoD/1/86",
  "title": "Registry of Deeds Transcript Book 86: memorials 1737",
  "pages": [
    {"page_key": "volA_p0.jpg", "label": "p0", "canvas_id": "https://api/iiif/v1/volA/canvas/p0"},
    {"page_key": "volA_p1.jpg", "label": "p1", "canvas_id": "https://api/iiif/v1/volA/canvas/p1"}
  ]
}
```

`tests/fixtures/archive/pages/volB/volume.json`:

```json
{
  "label": "PRONI Deeds Volume 25",
  "reference_code": "PRONI D4164/A/25",
  "title": "PRONI Deeds Volume 25: 1689",
  "pages": [
    {"page_key": "volB_p5.jpg", "label": "p5", "canvas_id": "https://api/iiif/v1/volB/canvas/p5"}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

In `tests/index/test_reader.py`, replace the existing `test_read_volume` (lines 68–72) with:

```python
def test_read_volume():
    vol = read_volume(FIXTURE / "pages" / "volA" / "volume.json", root_id="volA")
    assert vol.root_id == "volA"
    assert vol.label == "Registry of Deeds Transcript Book 86"
    assert vol.reference_code == "IMC 1954/RoD/1/86"
    assert vol.title == "Registry of Deeds Transcript Book 86: memorials 1737"
    assert [(p.page_key, p.ordinal, p.label) for p in vol.pages] == [
        ("volA_p0.jpg", 1, "p0"),
        ("volA_p1.jpg", 2, "p1"),
    ]


def test_read_volume_without_pages_yields_empty_list(tmp_path):
    path = tmp_path / "volume.json"
    path.write_text('{"label": "L", "reference_code": "R"}')
    vol = read_volume(path, root_id="volX")
    assert vol.title is None
    assert vol.pages == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/index/test_reader.py::test_read_volume tests/index/test_reader.py::test_read_volume_without_pages_yields_empty_list -v`
Expected: FAIL — `VolumeRow` has no `title`/`pages`; `AttributeError`.

- [ ] **Step 4: Implement the models**

In `src/vtextract/index/models.py`, add `VolumePage` and extend `VolumeRow` (lines 39–43) and `VolumeInfo` (lines 71–76). Keep `title`/`pages` after the existing positional fields with defaults so existing positional construction (`VolumeRow("volA", "Vol A", "REF-A")`) still works:

```python
@dataclass
class VolumePage:
    """One physical page of a volume, in sequence order."""

    page_key: str
    ordinal: int
    label: str | None = None


@dataclass
class VolumeRow:
    root_id: str
    label: str | None
    reference_code: str | None
    title: str | None = None
    pages: list[VolumePage] = field(default_factory=list)
```

```python
@dataclass
class VolumeInfo:
    root_id: str
    label: str | None
    reference_code: str | None
    item_count: int
    title: str | None = None
```

(`field` is already imported on line 6: `from dataclasses import dataclass, field`.)

- [ ] **Step 5: Implement `read_volume`**

In `src/vtextract/index/reader.py`, update the import on line 9 and replace `read_volume` (lines 68–74):

```python
from vtextract.index.models import ItemRow, PageLink, VolumePage, VolumeRow
```

```python
def read_volume(volume_path: Path, *, root_id: str) -> VolumeRow:
    data = json.loads(Path(volume_path).read_text())
    pages = [
        VolumePage(page_key=p["page_key"], ordinal=i, label=p.get("label"))
        for i, p in enumerate(data.get("pages") or [], start=1)
    ]
    return VolumeRow(
        root_id=root_id,
        label=data.get("label"),
        reference_code=data.get("reference_code"),
        title=data.get("title"),
        pages=pages,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/index/test_reader.py tests/index/test_models.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/index/models.py src/vtextract/index/reader.py tests/index/test_reader.py tests/fixtures/archive/pages/volA/volume.json tests/fixtures/archive/pages/volB/volume.json
git commit -m "feat: index reader parses volume title and ordered pages"
```

---

### Task 4: index schema — `page.ordinal`, `page.label`, `volume.title`, version bump

**Files:**
- Modify: `src/vtextract/index/db.py` (`SCHEMA_VERSION` line 11; `_DDL` lines 46–80)
- Test: `tests/index/test_db_schema.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/index/test_db_schema.py`:

```python
def test_page_and_volume_tables_have_new_columns(tmp_path):
    from vtextract.index.db import IndexDB
    with IndexDB(tmp_path / "index" / "vtindex.sqlite3") as db:
        page_cols = {r[1] for r in db._conn.execute("PRAGMA table_info(page)")}
        assert {"ordinal", "label"} <= page_cols
        vol_cols = {r[1] for r in db._conn.execute("PRAGMA table_info(volume)")}
        assert "title" in vol_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/index/test_db_schema.py::test_page_and_volume_tables_have_new_columns -v`
Expected: FAIL — `ordinal`/`label`/`title` columns absent.

- [ ] **Step 3: Implement**

In `src/vtextract/index/db.py`, bump the version (line 11):

```python
SCHEMA_VERSION = 2
```

In `_DDL` (lines 46–80), replace the `volume` and `page` table definitions:

```sql
CREATE TABLE volume (root_id TEXT PRIMARY KEY, label TEXT, reference_code TEXT, title TEXT);
CREATE TABLE page (
    root_id TEXT, page_key TEXT, ordinal INTEGER, label TEXT, has_text INTEGER,
    PRIMARY KEY (root_id, page_key)
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/index/test_db_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/db.py tests/index/test_db_schema.py
git commit -m "feat: add page ordinal/label and volume title columns (schema v2)"
```

---

### Task 5: `upsert_volume` writes title + ordinals; producers don't clobber; `delete_source`

**Files:**
- Modify: `src/vtextract/index/db.py` (`upsert_volume` lines 212–220; `upsert_transcription` lines 224–238; `delete_source` volume branch lines 270–272)
- Test: `tests/index/test_db_write.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/index/test_db_write.py` (it already imports `VolumeRow`; add `VolumePage`):

```python
from vtextract.index.models import ItemRow, PageLink, VolumePage, VolumeRow


def _vol(root_id="volA", **kw):
    base = dict(root_id=root_id, label="Vol A", reference_code="REF-A", title="Volume A",
                pages=[VolumePage("volA_p0.jpg", 1, "p0"), VolumePage("volA_p1.jpg", 2, "p1")])
    base.update(kw)
    return VolumeRow(**base)


def test_upsert_volume_inserts_pages_with_ordinals_and_title(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        assert db.counts()["pages"] == 2  # both pages indexed even without transcriptions
        rows = list(db._conn.execute(
            "SELECT page_key, ordinal, label, has_text FROM page WHERE root_id='volA' ORDER BY ordinal"))
        assert [(r["page_key"], r["ordinal"], r["label"], r["has_text"]) for r in rows] == [
            ("volA_p0.jpg", 1, "p0", 0),
            ("volA_p1.jpg", 2, "p1", 0),
        ]
        title = db._conn.execute("SELECT title FROM volume WHERE root_id='volA'").fetchone()[0]
        assert title == "Volume A"


def test_volume_then_transcription_preserves_both(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        db.upsert_transcription("volA", "volA_p1.jpg", "Houston of Dublin",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 9))
        row = db._conn.execute(
            "SELECT ordinal, label, has_text FROM page WHERE root_id='volA' AND page_key='volA_p1.jpg'"
        ).fetchone()
        assert (row["ordinal"], row["label"], row["has_text"]) == (2, "p1", 1)


def test_transcription_then_volume_preserves_both(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_transcription("volA", "volA_p1.jpg", "Houston of Dublin",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 9))
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        row = db._conn.execute(
            "SELECT ordinal, label, has_text FROM page WHERE root_id='volA' AND page_key='volA_p1.jpg'"
        ).fetchone()
        assert (row["ordinal"], row["label"], row["has_text"]) == (2, "p1", 1)


def test_upsert_volume_prunes_volume_only_pages_on_shrink(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        # reindex with a shorter list: volA_p0 drops out, volA_p1 stays
        db.upsert_volume(_vol(pages=[VolumePage("volA_p1.jpg", 1, "p1")]),
                         fingerprint=("pages/volA/volume.json", 2.0, 6))
        keys = [r["page_key"] for r in db._conn.execute(
            "SELECT page_key FROM page WHERE root_id='volA'")]
        assert keys == ["volA_p1.jpg"]


def test_upsert_volume_shrink_keeps_transcribed_page(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        db.upsert_transcription("volA", "volA_p0.jpg", "text",
                                fingerprint=("pages/volA/volA_p0.jpg.txt", 1.0, 4))
        # volA_p0 dropped from the volume list, but it has a transcription -> survives
        db.upsert_volume(_vol(pages=[VolumePage("volA_p1.jpg", 1, "p1")]),
                         fingerprint=("pages/volA/volume.json", 2.0, 6))
        row = db._conn.execute(
            "SELECT ordinal, has_text FROM page WHERE root_id='volA' AND page_key='volA_p0.jpg'"
        ).fetchone()
        assert row is not None
        assert (row["ordinal"], row["has_text"]) == (None, 1)  # ordering cleared, text kept


def test_delete_volume_source_clears_ordinals_and_drops_volume_only(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        db.upsert_transcription("volA", "volA_p1.jpg", "text",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 4))
        db.delete_source("pages/volA/volume.json")
        # volA_p0 was volume-only -> gone; volA_p1 has text -> stays, ordinal cleared
        rows = {r["page_key"]: r["ordinal"] for r in db._conn.execute(
            "SELECT page_key, ordinal FROM page WHERE root_id='volA'")}
        assert rows == {"volA_p1.jpg": None}
        assert db._conn.execute("SELECT COUNT(*) FROM volume WHERE root_id='volA'").fetchone()[0] == 0
```

Note the pre-existing `test_upsert_volume_and_transcription` (line 51) constructs `VolumeRow("volA", "Vol A", "REF-A")` with no pages; the new defaults make that a zero-page volume, so its `db.counts()["pages"] == 1` assertion (from the single transcription) still holds.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/index/test_db_write.py -k "volume or preserves or prune or shrink or delete_volume" -v`
Expected: FAIL — `upsert_volume` ignores `title`/`pages`; ordinals never written.

- [ ] **Step 3: Implement**

In `src/vtextract/index/db.py`, replace `upsert_volume` (lines 212–220):

```python
def upsert_volume(self, volume, *, fingerprint: tuple[str, float, int]) -> None:
    path, mtime, size = fingerprint
    self._conn.execute(
        "INSERT INTO volume (root_id, label, reference_code, title) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(root_id) DO UPDATE SET label=excluded.label, "
        "reference_code=excluded.reference_code, title=excluded.title",
        (volume.root_id, volume.label, volume.reference_code, volume.title),
    )
    # The volume page list is authoritative for page existence + ordinal + label.
    # Clear this volume's ordinals, (re)assign from the list, then prune
    # volume-only rows (has_text=0) no longer listed. Transcription-backed rows
    # survive with their ordering cleared if dropped from the list.
    self._conn.execute(
        "UPDATE page SET ordinal=NULL, label=NULL WHERE root_id=?", (volume.root_id,)
    )
    for page in volume.pages:
        self._conn.execute(
            "INSERT INTO page (root_id, page_key, ordinal, label, has_text) "
            "VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(root_id, page_key) DO UPDATE SET "
            "ordinal=excluded.ordinal, label=excluded.label",
            (volume.root_id, page.page_key, page.ordinal, page.label),
        )
    self._conn.execute(
        "DELETE FROM page WHERE root_id=? AND ordinal IS NULL AND has_text=0",
        (volume.root_id,),
    )
    self._set_fingerprint(path, "volume", mtime, size)
```

Replace the `INSERT OR REPLACE` in `upsert_transcription` (line 230) so it preserves any ordinal/label already set by volume indexing:

```python
        self._conn.execute(
            "INSERT INTO page (root_id, page_key, has_text) VALUES (?, ?, 1) "
            "ON CONFLICT(root_id, page_key) DO UPDATE SET has_text=1",
            (root_id, page_key),
        )
```

In `delete_source`, replace the `volume` branch (lines 270–272):

```python
    elif kind == "volume":
        root_id = path.split("/")[1]
        self._conn.execute("DELETE FROM volume WHERE root_id=?", (root_id,))
        self._conn.execute(
            "UPDATE page SET ordinal=NULL, label=NULL WHERE root_id=?", (root_id,)
        )
        self._conn.execute(
            "DELETE FROM page WHERE root_id=? AND ordinal IS NULL AND has_text=0",
            (root_id,),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/index/test_db_write.py -v`
Expected: PASS (including the pre-existing volume/transcription/delete tests).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/db.py tests/index/test_db_write.py
git commit -m "feat: volume indexing owns page ordinals; transcription owns has_text"
```

---

### Task 6: `db` page-lookup primitives + `volume`/`volumes()` carry `title`

**Files:**
- Modify: `src/vtextract/index/db.py` (`volumes` lines 373–387; add `get_page`, `page_at_ordinal`, `volume`)
- Test: `tests/index/test_db_write.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/index/test_db_write.py`:

```python
def test_get_page_and_page_at_ordinal(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        cur = db.get_page("volA", "volA_p1.jpg")
        assert cur["ordinal"] == 2 and cur["label"] == "p1"
        assert db.get_page("volA", "nope.jpg") is None
        prev = db.page_at_ordinal("volA", 1)
        assert prev["page_key"] == "volA_p0.jpg"
        assert db.page_at_ordinal("volA", 99) is None


def test_volume_lookup_and_volumes_include_title(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        assert db.volume("volA")["title"] == "Volume A"
        assert db.volume("missing") is None
        infos = {v.root_id: v for v in db.volumes()}
        assert infos["volA"].title == "Volume A"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/index/test_db_write.py -k "get_page or page_at_ordinal or volume_lookup" -v`
Expected: FAIL — `AttributeError: 'IndexDB' object has no attribute 'get_page'`; `VolumeInfo` carries no `title`.

- [ ] **Step 3: Implement**

In `src/vtextract/index/db.py`, replace `volumes` (lines 373–387) to select and pass `title`:

```python
def volumes(self) -> list[VolumeInfo]:
    """Return VolumeInfo for all volumes, ordered by root_id."""
    rows = self._conn.execute(
        "SELECT v.root_id, v.label, v.reference_code, v.title, "
        "(SELECT COUNT(DISTINCT iv.isadg_id) FROM item_volume iv "
        " WHERE iv.root_id = v.root_id) AS item_count "
        "FROM volume v ORDER BY v.root_id"
    )
    return [
        VolumeInfo(
            root_id=r["root_id"], label=r["label"],
            reference_code=r["reference_code"], item_count=r["item_count"],
            title=r["title"],
        )
        for r in rows
    ]


def volume(self, root_id: str) -> dict | None:
    """Return one volume row as a dict, or None."""
    row = self._conn.execute(
        "SELECT root_id, label, reference_code, title FROM volume WHERE root_id=?",
        (root_id,),
    ).fetchone()
    return dict(row) if row else None


def get_page(self, root_id: str, page_key: str) -> dict | None:
    """Return one page row (root_id, page_key, ordinal, label, has_text) or None."""
    row = self._conn.execute(
        "SELECT root_id, page_key, ordinal, label, has_text FROM page "
        "WHERE root_id=? AND page_key=?",
        (root_id, page_key),
    ).fetchone()
    return dict(row) if row else None


def page_at_ordinal(self, root_id: str, ordinal: int | None) -> dict | None:
    """Return the page at a given 1-based ordinal in a volume, or None."""
    if ordinal is None:
        return None
    row = self._conn.execute(
        "SELECT root_id, page_key, ordinal, label, has_text FROM page "
        "WHERE root_id=? AND ordinal=?",
        (root_id, ordinal),
    ).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/index/test_db_write.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/db.py tests/index/test_db_write.py
git commit -m "feat: db page-lookup primitives and volume title in listings"
```

---

### Task 7: `vtindex page` subcommand + `title` in `volumes` output

**Files:**
- Modify: `src/vtextract/index/cli.py` (`_cmd_volumes` lines 112–127; add `_cmd_page` + helpers; parser in `_build_parser` near line 305)
- Test: `tests/index/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/index/test_cli.py`. (The build in these tests is over the fixture archive, whose `volA` now has two pages `volA_p0.jpg`/`volA_p1.jpg` from Task 3.)

```python
def test_page_json_mid_volume_has_prev_and_next(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/volA_p1.jpg", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["current"]["page_key"] == "volA_p1.jpg"
    assert payload["current"]["ordinal"] == 2
    assert payload["previous"]["page_key"] == "volA_p0.jpg"
    assert payload["next"] is None  # volA_p1 is the last page
    assert payload["volume"]["title"] == "Registry of Deeds Transcript Book 86: memorials 1737"
    # current page's transcription path resolves (the .txt exists in the fixture)
    assert payload["current"]["transcription"].endswith("volA_p1.jpg.txt")


def test_page_json_first_page_has_no_previous(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/volA_p0.jpg", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["previous"] is None
    assert payload["next"]["page_key"] == "volA_p1.jpg"


def test_page_not_found_exit_1(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/nope.jpg", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert json.loads(out) is None


def test_page_bad_ref_exit_2(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "no-slash-here", "--archive", str(archive)])
    err = capsys.readouterr().err
    assert code == 2
    assert "root_id" in err


def test_page_without_ordinal_warns_exit_0(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    # Simulate a transcription-only page (no ordinal) by clearing it in the index.
    from vtextract.index.builder import INDEX_RELPATH
    import sqlite3
    conn = sqlite3.connect(archive / INDEX_RELPATH)
    conn.execute("UPDATE page SET ordinal=NULL WHERE root_id='volA' AND page_key='volA_p1.jpg'")
    conn.commit()
    conn.close()
    code = main(["page", "volA/volA_p1.jpg", "--archive", str(archive), "--json"])
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert code == 0
    assert payload["current"]["page_key"] == "volA_p1.jpg"
    assert payload["previous"] is None and payload["next"] is None
    assert "ordering" in out.err.lower()


def test_volumes_json_includes_title(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    main(["volumes", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    volA = next(v for v in payload if v["root_id"] == "volA")
    assert volA["title"] == "Registry of Deeds Transcript Book 86: memorials 1737"


def test_page_table_output_shows_paths(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/volA_p1.jpg", "--archive", str(archive)])
    out = capsys.readouterr().out
    assert code == 0
    assert "volA_p0.jpg" in out and "volA_p1.jpg" in out  # previous + current
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/index/test_cli.py -k "page or volumes_json_includes_title" -v`
Expected: FAIL — no `page` subcommand (argparse error / `SystemExit`); `volumes` JSON lacks `title`.

- [ ] **Step 3: Implement**

In `src/vtextract/index/cli.py`, add `title` to the `_cmd_volumes` data dict (lines 116–120) and its plain-text output (lines 124–126):

```python
    data = [
        {"root_id": v.root_id, "label": v.label,
         "reference_code": v.reference_code, "item_count": v.item_count,
         "title": v.title}
        for v in vols
    ]
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for d in data:
            print(f'{d["root_id"]}\t{d["item_count"]:>4}\t{d["title"] or d["label"] or ""}\t'
                  f'{d["reference_code"] or ""}')
```

Add a `_page_nav_dict` helper and `_cmd_page` (place them after `_result_dict`, near line 181):

```python
def _page_nav_dict(archive: Path, row: dict | None) -> dict | None:
    """Page navigation entry: file paths (_page_dict) plus ordinal and label."""
    if row is None:
        return None
    d = _page_dict(archive, row["root_id"], row["page_key"])
    d["ordinal"] = row["ordinal"]
    d["label"] = row["label"]
    return d


def _cmd_page(args) -> int:
    archive = _resolve_archive(args)
    if "/" not in args.ref:
        print("error: argument must be <root_id>/<page_key>", file=sys.stderr)
        return 2
    root_id, page_key = args.ref.split("/", 1)
    with _open_for_read(archive) as db:
        if is_stale(db, archive):
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        current = db.get_page(root_id, page_key)
        if current is None:
            if args.json:
                print(json.dumps(None))
            else:
                print(f"page not found: {args.ref}")
            return 1
        ordinal = current["ordinal"]
        if ordinal is None:
            print("warning: page ordering unavailable (re-extract this volume to "
                  "regenerate volume.json).", file=sys.stderr)
            previous = nxt = None
        else:
            previous = db.page_at_ordinal(root_id, ordinal - 1)
            nxt = db.page_at_ordinal(root_id, ordinal + 1)
        volume = db.volume(root_id) or {"root_id": root_id, "title": None}
    nav = {
        "volume": {"root_id": root_id, "title": volume.get("title")},
        "previous": _page_nav_dict(archive, previous),
        "current": _page_nav_dict(archive, current),
        "next": _page_nav_dict(archive, nxt),
    }
    if args.json:
        print(json.dumps(nav, indent=2))
    else:
        _print_page_nav(nav, volume.get("title"))
    return 0


def _print_page_nav(nav: dict, title: str | None) -> None:
    table = Table(show_header=True, title=title or nav["volume"]["root_id"])
    table.add_column("Position", no_wrap=True)
    table.add_column("Ordinal", no_wrap=True)
    table.add_column("Label", no_wrap=True)
    table.add_column("Image")
    for position in ("previous", "current", "next"):
        entry = nav[position]
        if entry is None:
            continue
        table.add_row(
            position,
            str(entry["ordinal"]) if entry["ordinal"] is not None else "-",
            entry["label"] or "-",
            entry["image"] or entry["page_key"],
        )
    Console().print(table)
```

Register the subcommand in `_build_parser` (after the `volumes` parser, around line 308):

```python
    p_page = sub.add_parser("page", help="show a page's previous/next neighbours")
    p_page.add_argument("ref", help="page reference as <root_id>/<page_key>")
    _add_archive_args(p_page)
    p_page.add_argument("--json", action="store_true")
    p_page.set_defaults(func=_cmd_page)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/index/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/cli.py tests/index/test_cli.py
git commit -m "feat: add vtindex page command and volume title in volumes output"
```

---

### Task 8: Full-suite verification + README note

**Files:**
- Modify: `README.md` (vtindex usage section)
- Modify: `CLAUDE.md` (Index CLI bullet under "Running things")

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest`
Expected: PASS — every test, no network access. If anything fails, fix it before continuing.

- [ ] **Step 2: Smoke-test the new command against the real archive**

The real archive's existing `volume.json` files predate Task 1, so a fresh `--rebuild` is needed and pages will only carry ordinals for volumes re-extracted since. Confirm the command runs and degrades gracefully:

Run:
```bash
.venv/bin/vtindex build --rebuild --archive /Users/andrew/.vt/archive
.venv/bin/vtindex page 504339/sp063-356-000_0076_74.jpg --archive /Users/andrew/.vt/archive --json
```
Expected: the schema-v2 rebuild succeeds; the command prints a JSON object. For a not-yet-re-extracted volume it prints the current page with a stderr "ordering unavailable" warning and exits 0 — this is correct per the migration decision (re-extract to populate ordering).

- [ ] **Step 3: Document the feature**

In `README.md`, under the vtindex usage, add a line documenting the new command:

```markdown
- `vtindex page <root_id>/<page_key>` — show a page's previous / current / next
  neighbours in its volume, with resolved file paths (`--json` for structured
  output). Page ordering comes from the volume's `volume.json`, which is written
  during extraction with `--context-pages >= 1`; re-extract an existing archive
  to populate ordering for older volumes.
```

In `CLAUDE.md`, update the Index CLI bullet (currently `build`/`search`) to also mention `page`:

```markdown
- **Index CLI:** `.venv/bin/vtindex build --archive ./archive` then
  `.venv/bin/vtindex search "<keyword>" --archive ./archive [--json]`, or
  `.venv/bin/vtindex page <rootID>/<page_key> --archive ./archive` for
  previous/next page navigation within a volume.
```

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document vtindex page command and volume ordering"
```

---

## Notes for the implementer

- **Run order matters:** Tasks 1→8 are sequential; later tasks import names defined earlier (`detail_title`, `VolumePage`, `db.get_page`, etc.).
- **Schema v2 is a hard break** for any pre-existing index: `vtindex build` on an old DB raises `SchemaMismatch` instructing a `--rebuild`. That is intended.
- **The two-producer invariant is the subtle part** (Task 5): volume indexing owns `ordinal`/`label` and page *existence*; transcription indexing owns `has_text`. Each `ON CONFLICT DO UPDATE` touches only its own columns. The "shrink keeps transcribed page" and "delete clears ordinals" tests guard this — do not let them regress.
- **No network, ever:** all tests use committed fixtures or synthetic dicts; `client` is always a `httpx.MockTransport`.
