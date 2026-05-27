# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from pathlib import Path

from vtextract.index.reader import (
    compose_description,
    date_bounds,
    read_item,
    read_transcription,
    read_volume,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def test_read_item_core_fields():
    row = read_item(FIXTURE / "items" / "100" / "metadata.json")
    assert row.isadg_id == 100
    assert row.reference_code == "FIX 1/A/1"
    assert row.repository == "Registry of Deeds"
    assert "Houston" in row.title or "HOUSTON" in row.title
    assert row.content_begin == "1737-05-06" and row.content_end == "1737-05-06"
    assert row.created_begin == "1737-01-18"
    assert row.path == "items/100"


def test_read_item_description_concatenates_fields():
    row = read_item(FIXTURE / "items" / "100" / "metadata.json")
    assert "seal and a memorial" in row.description
    assert "Abstract of a will" in row.description


def test_read_item_volumes_and_pages():
    row = read_item(FIXTURE / "items" / "200" / "metadata.json")
    assert set(row.volumes) == {"volA", "volB"}
    primary = [p for p in row.pages if p.role == "primary"]
    assert {(p.root_id, p.page_key) for p in primary} == {
        ("volA", "volA_p1.jpg"), ("volB", "volB_p5.jpg")
    }


def test_read_item_missing_created_date_is_none():
    row = read_item(FIXTURE / "items" / "300" / "metadata.json")
    assert row.created_begin is None and row.created_end is None
    assert row.content_begin == "1689-01-01" and row.content_end == "1689-12-31"


def test_date_bounds_content_and_created():
    hit = {
        "contentDate": {"gte": "1737-05-06", "lte": "1737-05-06"},
        "createdDate": {"gte": "1737-01-18", "lte": "1737-01-18"},
    }
    assert date_bounds(hit, "content") == ("1737-05-06", "1737-05-06")
    assert date_bounds(hit, "created") == ("1737-01-18", "1737-01-18")
    assert date_bounds({}, "content") == (None, None)


def test_compose_description_skips_empty_lists():
    hit = {
        "scopeAndContent": ["A.", "B."],
        "archivalHistory": [],
        "note": ["C."],
    }
    assert compose_description(hit) == "A.\nB.\nC."


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


def test_read_transcription_reads_text():
    text = read_transcription(FIXTURE / "pages" / "volA" / "volA_p1.jpg.txt")
    assert "John Houston of Dublin" in text
