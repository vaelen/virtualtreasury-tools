# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import shutil
from pathlib import Path

from vtextract.index.builder import build
from vtextract.index.db import IndexDB

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def _copy_archive(tmp_path) -> Path:
    dest = tmp_path / "archive"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_full_build_indexes_everything(tmp_path):
    archive = _copy_archive(tmp_path)
    stats = build(archive)
    # 3 items + 2 volume.json + 3 transcription .txt (volA_p1, volA_p0, volB_p5) = 8
    assert stats.added == 8
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        c = db.counts()
    assert c["items"] == 3
    assert c["volumes"] == 2
    assert c["pages"] == 3  # one page row per transcription on disk


def test_incremental_skips_unchanged(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    stats2 = build(archive)
    assert stats2.added == 0 and stats2.updated == 0 and stats2.removed == 0
    assert stats2.unchanged > 0


def test_incremental_detects_change(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    meta = archive / "items" / "300" / "metadata.json"
    text = meta.read_text().replace("Galway", "Mayo")
    meta.write_text(text)
    # bump mtime to be safe across fast filesystems
    import os, time
    os.utime(meta, (time.time() + 5, time.time() + 5))
    stats = build(archive)
    assert stats.updated == 1
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        rows = list(db._conn.execute(
            "SELECT rowid FROM item_fts WHERE item_fts MATCH ?", ("Mayo",)))
    assert rows and rows[0]["rowid"] == 300


def test_incremental_removes_vanished(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    shutil.rmtree(archive / "items" / "300")
    stats = build(archive)
    assert stats.removed == 1
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        assert db.counts()["items"] == 2


def test_malformed_metadata_is_skipped(tmp_path):
    archive = _copy_archive(tmp_path)
    (archive / "items" / "999").mkdir()
    (archive / "items" / "999" / "metadata.json").write_text("{ not json")
    stats = build(archive)
    assert stats.skipped == 1
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        assert db.counts()["items"] == 3  # the 3 good ones only


def test_rebuild_flag_starts_fresh(tmp_path):
    archive = _copy_archive(tmp_path)
    build(archive)
    stats = build(archive, rebuild=True)
    assert stats.added > 0 and stats.unchanged == 0


# --- estimated_date fallback ---

def _write_estimated_fixture(archive: Path) -> None:
    """Lay out an archive with three items exercising the estimated_date paths.

    - item 400: no isadgDates, title without a year, linked to a volume whose
      title contains a year   → estimated_source == "volume".
    - item 500: no isadgDates, year in item title, linked to a volume with no
      year in title             → estimated_source == "item_title".
    - item 600: no isadgDates, title is purely a catalogue path, linked to the
      same year-less volume      → estimated_begin/end is None.
    """
    import json

    pages = archive / "pages"
    items = archive / "items"
    (pages / "volX").mkdir(parents=True)
    (pages / "volY").mkdir(parents=True)
    # volX has a year in title; volY does not.
    (pages / "volX" / "volume.json").write_text(json.dumps({
        "label": "Test Book X",
        "reference_code": "TEST 1/A/X",
        "title": "Test Book X: memorials 1737",
        "pages": [{"page_key": "volX_p0.jpg", "label": "p0"}],
    }))
    (pages / "volY" / "volume.json").write_text(json.dumps({
        "label": "Test Book Y",
        "reference_code": "TEST 1/A/Y",
        "title": "Test Book Y (no year)",
        "pages": [{"page_key": "volY_p0.jpg", "label": "p0"}],
    }))
    for isadg_id, ref, title, root_id in (
        (400, "TEST 1/A/X/1", "Untitled record", "volX"),
        (500, "TEST 1/A/Y/1", "Patent letters 1801", "volY"),
        (600, "IMC 1954/RoD/1", "IMC 1954/RoD/1", "volY"),
    ):
        (items / str(isadg_id)).mkdir(parents=True)
        (items / str(isadg_id) / "metadata.json").write_text(json.dumps({
            "isadgID": isadg_id,
            "referenceCode": ref,
            "title": title,
            "pages": [{"page_key": f"{root_id}_p0.jpg", "root_id": root_id,
                       "role": "primary"}],
            "detail": {"id": isadg_id, "isadgDates": []},
        }))


def _estimated_row(archive: Path, isadg_id: int) -> dict:
    with IndexDB(archive / "index" / "vtindex.sqlite3") as db:
        row = db._conn.execute(
            "SELECT estimated_begin, estimated_end, estimated_source "
            "FROM item WHERE isadg_id=?",
            (isadg_id,),
        ).fetchone()
    return dict(row)


def test_estimated_date_from_volume_title(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _write_estimated_fixture(archive)
    build(archive)
    row = _estimated_row(archive, 400)
    assert row["estimated_begin"] == "1737-01-01"
    assert row["estimated_end"] == "1737-12-31"
    assert row["estimated_source"] == "volume"


def test_estimated_date_from_item_title_when_volume_has_none(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _write_estimated_fixture(archive)
    build(archive)
    row = _estimated_row(archive, 500)
    assert row["estimated_begin"] == "1801-01-01"
    assert row["estimated_end"] == "1801-12-31"
    assert row["estimated_source"] == "item_title"


def test_estimated_date_ignores_reference_code_in_title(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _write_estimated_fixture(archive)
    build(archive)
    row = _estimated_row(archive, 600)
    assert row["estimated_begin"] is None
    assert row["estimated_end"] is None
    assert row["estimated_source"] is None


def test_estimated_date_computed_even_when_metadata_dates_present(tmp_path):
    """Items that already have content_date still get an estimated_date stored,
    so display layers can compare provenance later."""
    archive = _copy_archive(tmp_path)
    build(archive)
    # Item 300 has a content date AND its volume (volB) title is "PRONI Deeds
    # Volume 25: 1689" — both should populate.
    row = _estimated_row(archive, 300)
    assert row["estimated_begin"] == "1689-01-01"
    assert row["estimated_end"] == "1689-12-31"
    assert row["estimated_source"] == "volume"


def test_build_cancel_stops_and_does_not_prune(tmp_path):
    import shutil
    import threading
    from pathlib import Path
    from vtextract.index.builder import INDEX_RELPATH, build
    from vtextract.index.db import IndexDB

    FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)

    # Full build first so source_file fingerprints exist.
    build(archive)

    # Now a cancel that is already set: the loop should process nothing new and,
    # crucially, must NOT prune the existing source_file rows.
    cancel = threading.Event()
    cancel.set()
    build(archive, cancel=cancel)

    db = IndexDB(archive / INDEX_RELPATH)
    try:
        remaining = db.counts()["source_files"]
    finally:
        db.close()
    assert remaining > 0, "cancelled build must not prune existing sources"


def test_build_ingests_names_sidecar(tmp_path):
    from vtextract.index.builder import build, INDEX_RELPATH
    from vtextract.index.db import IndexDB
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "a.jpg.names.json").write_text(
        '{"schema":2,"model":"m","people":[["William Young","Wm Young"]]}'
    )
    stats = build(tmp_path)
    assert stats.added >= 1
    db = IndexDB(tmp_path / INDEX_RELPATH)
    assert db.person_fts_search("Young")[0]["canonical"] == "William Young"
    db.close()
