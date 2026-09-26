# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from vtextract.index.db import IndexDB
from vtextract.index.models import ItemRow, PageLink, VolumePage, VolumeRow


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


def test_filter_items_content_falls_back_to_estimated(tmp_path):
    # An item with no catalogued content date but an estimated range must be
    # found by a content-date search overlapping that estimate.
    with _db(tmp_path) as db:
        db.upsert_item(
            _item(isadg_id=521, content_begin=None, content_end=None,
                  estimated_begin="1776-01-01", estimated_end="1793-12-31",
                  estimated_source="volume"),
            fingerprint=("items/521/metadata.json", 1.0, 10))
        rows = db.filter_items(None, date_type="content",
                               date_from="1780-01-01", date_to="1780-12-31")
        assert [r["isadg_id"] for r in rows] == [521]


def test_filter_items_content_date_takes_precedence_over_estimated(tmp_path):
    # When a real content date exists it is authoritative — the estimate is
    # ignored, even if it would have matched.
    with _db(tmp_path) as db:
        db.upsert_item(
            _item(isadg_id=900, content_begin="1850-01-01", content_end="1850-12-31",
                  estimated_begin="1737-01-01", estimated_end="1737-12-31",
                  estimated_source="item_title"),
            fingerprint=("items/900/metadata.json", 1.0, 10))
        assert db.filter_items(None, date_type="content",
                               date_from="1737-01-01", date_to="1737-12-31") == []
        rows = db.filter_items(None, date_type="content",
                               date_from="1850-01-01", date_to="1850-12-31")
        assert [r["isadg_id"] for r in rows] == [900]


def test_filter_items_created_does_not_fall_back_to_estimated(tmp_path):
    # The estimate is a content-coverage guess, not a record-creation date:
    # a created-date search must not use it.
    with _db(tmp_path) as db:
        db.upsert_item(
            _item(isadg_id=521, content_begin=None, content_end=None,
                  created_begin=None, created_end=None,
                  estimated_begin="1776-01-01", estimated_end="1793-12-31",
                  estimated_source="volume"),
            fingerprint=("items/521/metadata.json", 1.0, 10))
        rows = db.filter_items(None, date_type="created",
                               date_from="1780-01-01", date_to="1780-12-31")
        assert rows == []


def test_filter_items_orders_estimated_only_by_effective_date(tmp_path):
    # Filter-only output is ordered chronologically; an estimated-only item
    # sorts by its estimated year, interleaved with content-dated items.
    with _db(tmp_path) as db:
        db.upsert_item(
            _item(isadg_id=100, content_begin="1737-01-01", content_end="1737-12-31"),
            fingerprint=("items/100/metadata.json", 1.0, 10))
        db.upsert_item(
            _item(isadg_id=521, content_begin=None, content_end=None,
                  estimated_begin="1700-01-01", estimated_end="1700-12-31",
                  estimated_source="volume"),
            fingerprint=("items/521/metadata.json", 1.0, 10))
        db.upsert_item(
            _item(isadg_id=900, content_begin=None, content_end=None,
                  estimated_begin="1800-01-01", estimated_end="1800-12-31",
                  estimated_source="volume"),
            fingerprint=("items/900/metadata.json", 1.0, 10))
        rows = db.filter_items(None)
        assert [r["isadg_id"] for r in rows] == [521, 100, 900]  # 1700, 1737, 1800


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
        db.upsert_volume(_vol(pages=[VolumePage("volA_p1.jpg", 1, "p1")]),
                         fingerprint=("pages/volA/volume.json", 2.0, 6))
        row = db._conn.execute(
            "SELECT ordinal, has_text FROM page WHERE root_id='volA' AND page_key='volA_p0.jpg'"
        ).fetchone()
        assert row is not None
        assert (row["ordinal"], row["has_text"]) == (None, 1)  # ordering cleared, text kept


def test_delete_transcription_source_keeps_volume_owned_page(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        db.upsert_transcription("volA", "volA_p1.jpg", "Houston",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 7))
        db.delete_source("pages/volA/volA_p1.jpg.txt")
        row = db._conn.execute(
            "SELECT ordinal, has_text FROM page WHERE root_id='volA' AND page_key='volA_p1.jpg'"
        ).fetchone()
        assert row is not None, "volume-owned page must survive transcription deletion"
        assert row["ordinal"] == 2   # ordinal preserved
        assert row["has_text"] == 0  # text flag cleared
        assert list(db._conn.execute("SELECT * FROM transcription_map")) == []


def test_delete_volume_source_clears_ordinals_and_drops_volume_only(tmp_path):
    with _db(tmp_path) as db:
        db.upsert_volume(_vol(), fingerprint=("pages/volA/volume.json", 1.0, 5))
        db.upsert_transcription("volA", "volA_p1.jpg", "text",
                                fingerprint=("pages/volA/volA_p1.jpg.txt", 1.0, 4))
        db.delete_source("pages/volA/volume.json")
        rows = {r["page_key"]: r["ordinal"] for r in db._conn.execute(
            "SELECT page_key, ordinal FROM page WHERE root_id='volA'")}
        assert rows == {"volA_p1.jpg": None}
        assert db._conn.execute("SELECT COUNT(*) FROM volume WHERE root_id='volA'").fetchone()[0] == 0


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


def test_person_upsert_and_fts_search(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    rows = [PersonRow(canonical="William Young",
                      aliases=["Wm Young", "Young"])]
    db.upsert_names("100", "a.jpg", rows, fingerprint=("pages/100/a.jpg.names.json", 1.0, 10))
    hits = db.person_fts_search("Wm Young")
    assert len(hits) == 1
    assert hits[0]["canonical"] == "William Young"
    assert (hits[0]["root_id"], hits[0]["page_key"]) == ("100", "a.jpg")
    # alias text is searchable too
    assert db.person_fts_search("Young")
    assert db.counts()["people"] == 1
    db.close()


def test_person_reupsert_replaces_page(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    fp = ("pages/100/a.jpg.names.json", 1.0, 10)
    db.upsert_names("100", "a.jpg", [PersonRow("John Young")], fingerprint=fp)
    db.upsert_names("100", "a.jpg", [PersonRow("Thomas Young")], fingerprint=fp)
    names = {h["canonical"] for h in db.person_fts_search("Young")}
    assert names == {"Thomas Young"}  # old row replaced
    db.close()


def test_delete_source_names(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    rel = "pages/100/a.jpg.names.json"
    db.upsert_names("100", "a.jpg", [PersonRow("John Young")], fingerprint=(rel, 1.0, 10))
    db.delete_source(rel)
    assert db.person_fts_search("Young") == []
    assert db.counts()["people"] == 0
    db.close()
