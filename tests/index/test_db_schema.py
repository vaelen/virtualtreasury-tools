# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import sqlite3

import pytest

from vtextract.index.db import IndexDB, SCHEMA_VERSION, SchemaMismatch, fts5_available


def test_fts5_available_true_on_this_interpreter():
    assert fts5_available() is True


def test_open_creates_schema_and_version(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        assert db.get_meta("schema_version") == str(SCHEMA_VERSION)
        tables = {
            r[0]
            for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"meta", "item", "volume", "page", "item_volume", "item_page",
                "source_file", "transcription_map"} <= tables
    assert db_path.exists()  # parent dir created


def test_reopen_same_version_keeps_data(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        db.set_meta("probe", "1")
    with IndexDB(db_path) as db:
        assert db.get_meta("probe") == "1"


def test_version_mismatch_raises(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        db.set_meta("schema_version", "0")
    with pytest.raises(SchemaMismatch):
        IndexDB(db_path)


def test_rebuild_drops_and_recreates(tmp_path):
    db_path = tmp_path / "index" / "vtindex.sqlite3"
    with IndexDB(db_path) as db:
        db.set_meta("probe", "1")
    with IndexDB(db_path, rebuild=True) as db:
        assert db.get_meta("probe") is None
        assert db.get_meta("schema_version") == str(SCHEMA_VERSION)


def test_page_and_volume_tables_have_new_columns(tmp_path):
    from vtextract.index.db import IndexDB
    with IndexDB(tmp_path / "index" / "vtindex.sqlite3") as db:
        page_cols = {r[1] for r in db._conn.execute("PRAGMA table_info(page)")}
        assert {"ordinal", "label"} <= page_cols
        vol_cols = {r[1] for r in db._conn.execute("PRAGMA table_info(volume)")}
        assert "title" in vol_cols


def test_item_table_has_estimated_date_columns(tmp_path):
    with IndexDB(tmp_path / "index" / "vtindex.sqlite3") as db:
        item_cols = {r[1] for r in db._conn.execute("PRAGMA table_info(item)")}
        assert {"estimated_begin", "estimated_end", "estimated_source"} <= item_cols


def test_item_fts_does_not_include_dates(tmp_path):
    """Dates filter via structured columns, not FTS."""
    with IndexDB(tmp_path / "index" / "vtindex.sqlite3") as db:
        fts_cols = {r[1] for r in db._conn.execute("PRAGMA table_info(item_fts)")}
        assert "estimated_begin" not in fts_cols
        assert "estimated_end" not in fts_cols
        assert "estimated_source" not in fts_cols
