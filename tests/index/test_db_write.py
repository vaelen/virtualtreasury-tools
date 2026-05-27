# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.index.db import IndexDB
from vtextract.index.models import ItemRow, PageLink, VolumeRow


def _db(tmp_path):
    return IndexDB(tmp_path / "index" / "vtindex.sqlite3")


def _item(**kw):
    base = dict(
        isadg_id=100, reference_code="R", title="Houston will", description="a seal",
        repository="RoD", content_begin="1737-05-06", content_end="1737-05-06",
        volumes=["volA"], pages=[PageLink("volA", "volA_p1.jpg", "primary")],
    )
    base.update(kw)
    return ItemRow(**base)


def test_upsert_item_inserts_rows_and_fts(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_item(_item(), fingerprint=("items/100/metadata.json", 1.0, 10))
        assert db.counts()["items"] == 1
        assert db.counts()["item_volume"] == 1
        assert db.counts()["item_page"] == 1
        # item_fts row keyed by isadg_id
        hit = {r["rowid"]: r for r in db._conn.execute(
            "SELECT rowid, title FROM item_fts WHERE item_fts MATCH ?", ("houston",))}
        assert 100 in hit


def test_upsert_item_replaces_on_reindex(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_item(_item(), fingerprint=("items/100/metadata.json", 1.0, 10))
        db.upsert_item(
            _item(title="Changed title", volumes=["volB"],
                  pages=[PageLink("volB", "volB_p5.jpg", "primary")]),
            fingerprint=("items/100/metadata.json", 2.0, 12),
        )
        assert db.counts()["items"] == 1
        assert db.counts()["item_volume"] == 1
        rows = list(db._conn.execute("SELECT root_id FROM item_volume WHERE isadg_id=100"))
        assert rows[0]["root_id"] == "volB"
        old = list(db._conn.execute(
            "SELECT rowid FROM item_fts WHERE item_fts MATCH ?", ("Houston",)))
        assert old == []  # old title text gone


def test_upsert_volume_and_transcription(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(VolumeRow("volA", "Vol A", "REF-A"),
                         fingerprint=("pages/volA/volume.json", 1.0, 5))
        db.upsert_transcription("volA", "volA_p1.jpg", "Houston of Dublin",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 9))
        assert db.counts()["volumes"] == 1
        assert db.counts()["pages"] == 1
        rows = list(db._conn.execute(
            "SELECT tm.root_id, tm.page_key FROM transcription_fts f "
            "JOIN transcription_map tm ON tm.rowid = f.rowid "
            "WHERE transcription_fts MATCH ?", ("dublin",)))
        assert (rows[0]["root_id"], rows[0]["page_key"]) == ("volA", "volA_p1.jpg")


def test_fingerprints_and_delete_source(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_item(_item(), fingerprint=("items/100/metadata.json", 1.5, 10))
        fps = db.fingerprints()
        assert fps["items/100/metadata.json"] == (1.5, 10)
        db.delete_source("items/100/metadata.json")
        assert db.counts()["items"] == 0
        assert "items/100/metadata.json" not in db.fingerprints()


def test_delete_transcription_source_removes_fts(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_transcription("volA", "volA_p1.jpg", "Houston",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 7))
        db.delete_source("pages/volA/volA_p1.jpg.txt")
        assert db.counts()["pages"] == 0
        assert list(db._conn.execute("SELECT * FROM transcription_map")) == []
