# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from pathlib import Path

from vtextract.index.reader import (
    compose_description,
    date_bounds,
    page_files,
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


def test_date_bounds_reads_isadg_dates_by_event_type():
    detail = {
        "isadgDates": [
            {"eventType": {"name": "Created"},
             "timespan": {"beginOfBegin": "1737-01-18", "endOfEnd": "1737-01-18"}},
            {"eventType": {"name": "Content Date"},
             "timespan": {"beginOfBegin": "1737-05-06", "endOfEnd": "1737-05-06"}},
        ]
    }
    assert date_bounds(detail, "content") == ("1737-05-06", "1737-05-06")
    assert date_bounds(detail, "created") == ("1737-01-18", "1737-01-18")
    assert date_bounds({}, "content") == (None, None)


def test_date_bounds_uses_outer_span_for_ranges():
    # A PERIOD timespan: begin bound is beginOfBegin, end bound is endOfEnd.
    detail = {
        "isadgDates": [
            {"eventType": {"name": "Content Date"},
             "timespan": {"beginOfBegin": "1689-01-01", "endOfBegin": "1689-01-01",
                          "beginOfEnd": "1689-12-31", "endOfEnd": "1689-12-31"}},
        ]
    }
    assert date_bounds(detail, "content") == ("1689-01-01", "1689-12-31")
    assert date_bounds(detail, "created") == (None, None)


def test_compose_description_joins_detail_fields_in_order():
    detail = {
        "isadgContentAndStructure": [{"scopeAndContent": "A."}],
        "isadgContexts": [{"archivalHistory": "B.", "administrativeOrBiographicalHistory": None}],
        "isadgDescriptionControls": [{"archivistsNote": None}],
        "isadgNotes": [{"note": "C."}],
    }
    assert compose_description(detail) == "A.\nB.\nC."


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


def test_page_files_resolves_existing_and_absent(tmp_path):
    page_dir = tmp_path / "pages" / "volA"
    page_dir.mkdir(parents=True)
    (page_dir / "volA_p1.jpg.txt").write_text("hello")
    pf = page_files(tmp_path, "volA", "volA_p1.jpg")
    assert pf.transcription == str((page_dir / "volA_p1.jpg.txt").resolve())
    assert pf.image is None
    assert pf.metadata is None


def test_page_files_resolves_image_and_metadata(tmp_path):
    page_dir = tmp_path / "pages" / "volA"
    page_dir.mkdir(parents=True)
    (page_dir / "volA_p1.jpg").write_text("img")
    (page_dir / "volA_p1.jpg.json").write_text("{}")
    pf = page_files(tmp_path, "volA", "volA_p1.jpg")
    assert pf.image == str((page_dir / "volA_p1.jpg").resolve())
    assert pf.metadata == str((page_dir / "volA_p1.jpg.json").resolve())
    assert pf.transcription is None


def test_read_names(tmp_path):
    from vtextract.index.reader import read_names
    side = tmp_path / "a.jpg.names.json"
    side.write_text(
        '{"schema": 2, "model": "m", "people": ['
        '["William Young", "Wm Young", "Young"]]}'
    )
    people = read_names(side)
    assert len(people) == 1
    assert people[0].canonical == "William Young"
    assert people[0].aliases == ["Wm Young", "Young"]


def test_read_names_empty(tmp_path):
    from vtextract.index.reader import read_names
    side = tmp_path / "b.jpg.names.json"
    side.write_text('{"schema": 2, "model": "m", "people": []}')
    assert read_names(side) == []


def test_page_files_resolves_names_and_notes_sidecars(tmp_path):
    page_dir = tmp_path / "pages" / "volA"
    page_dir.mkdir(parents=True)
    (page_dir / "volA_p1.jpg.names.json").write_text("{}")
    (page_dir / "volA_p1.jpg.notes.md").write_text("note")
    pf = page_files(tmp_path, "volA", "volA_p1.jpg")
    assert pf.names == str((page_dir / "volA_p1.jpg.names.json").resolve())
    assert pf.notes == str((page_dir / "volA_p1.jpg.notes.md").resolve())
    assert page_files(tmp_path, "volA", "volA_p2.jpg").names is None
    assert page_files(tmp_path, "volA", "volA_p2.jpg").notes is None
