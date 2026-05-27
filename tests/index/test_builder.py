# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

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
