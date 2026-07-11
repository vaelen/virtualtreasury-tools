# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import shutil
from pathlib import Path

from vtextract.index.builder import build
from vtextract.index.db import IndexDB
from vtextract.index.models import SearchQuery
from vtextract.index.query import search

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def _built(tmp_path) -> IndexDB:
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    build(archive)
    return IndexDB(archive / "index" / "vtindex.sqlite3")


def test_keyword_in_title(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="Houston", fields=("title",)))
    ids = [r.isadg_id for r in results]
    assert ids == [100]
    assert "title" in results[0].matched_fields


def test_keyword_in_description(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="memorial", fields=("description",)))
    assert [r.isadg_id for r in results] == [100]
    assert "description" in results[0].matched_fields


def test_keyword_in_transcription_resolves_to_items(tmp_path):
    # "Houston" appears in volA_p1.jpg.txt, a page shared by items 100 and 200.
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="Houston", fields=("transcription",)))
    ids = sorted(r.isadg_id for r in results)
    assert ids == [100, 200]
    r100 = next(r for r in results if r.isadg_id == 100)
    assert ("volA", "volA_p1.jpg", "primary") in r100.matched_pages
    assert "transcription" in r100.matched_fields


def test_all_fields_default(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="Cork"))
    # "Cork" is in item 200 title+description and in volB_p5 transcription
    assert [r.isadg_id for r in results] == [200]


def test_date_filter_content_overlap(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(date_from="1700-01-01", date_to="1740-12-31"))
    ids = sorted(r.isadg_id for r in results)
    assert ids == [100]  # 1737 content date; 200 is 1751, 300 is 1689


def test_date_filter_year_bounds_via_iso(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(date_from="1689-01-01", date_to="1689-12-31"))
    assert [r.isadg_id for r in results] == [300]


def test_created_date_type(tmp_path):
    with _built(tmp_path) as db:
        results = search(
            db, SearchQuery(date_type="created", date_from="1737-01-01", date_to="1737-01-31"))
    assert [r.isadg_id for r in results] == [100]  # created 1737-01-18


def test_volume_filter(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(volume="volB"))
    ids = sorted(r.isadg_id for r in results)
    assert ids == [200, 300]  # both reference volB


def test_filter_only_no_text_returns_all_sorted_by_date(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery())
    ids = [r.isadg_id for r in results]
    assert ids == [300, 100, 200]  # 1689, 1737, 1751 ascending by content_begin


def test_limit(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(limit=1))
    assert len(results) == 1


def test_limit_zero_returns_all(tmp_path):
    with _built(tmp_path) as db:
        all_results = search(db, SearchQuery())
        unlimited = search(db, SearchQuery(limit=0))
    assert [r.isadg_id for r in unlimited] == [r.isadg_id for r in all_results]


def test_limit_zero_with_offset(tmp_path):
    with _built(tmp_path) as db:
        all_results = search(db, SearchQuery())
        rest = search(db, SearchQuery(limit=0, offset=1))
    assert [r.isadg_id for r in rest] == [r.isadg_id for r in all_results[1:]]


def test_offset_skips_leading_results(tmp_path):
    with _built(tmp_path) as db:
        all_results = search(db, SearchQuery())
        offset_results = search(db, SearchQuery(offset=1))
    assert [r.isadg_id for r in offset_results] == [r.isadg_id for r in all_results[1:]]


def test_offset_and_limit_paginate(tmp_path):
    with _built(tmp_path) as db:
        page1 = search(db, SearchQuery(limit=1, offset=0))
        page2 = search(db, SearchQuery(limit=1, offset=1))
        page3 = search(db, SearchQuery(limit=1, offset=2))
    assert [r.isadg_id for r in page1] == [300]
    assert [r.isadg_id for r in page2] == [100]
    assert [r.isadg_id for r in page3] == [200]


def test_offset_past_end_returns_empty(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(offset=999))
    assert results == []


def test_keyword_and_date_combine(tmp_path):
    with _built(tmp_path) as db:
        results = search(
            db, SearchQuery(text="Houston", date_from="1900-01-01", date_to="1950-12-31"))
    assert results == []  # keyword matches 100 but date excludes it


def test_keyword_with_punctuation_is_safe(tmp_path):
    # "Mitchell, Rose" has a comma; must match item 200's title without crashing.
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="Mitchell, Rose", fields=("title",)))
    assert [r.isadg_id for r in results] == [200]


def test_keyword_apostrophe_does_not_crash(tmp_path):
    # No fixture has an apostrophe name; this must return [] (not raise).
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(text="O'Brien"))
    assert results == []


def test_search_result_carries_estimated_date_from_volume_title(tmp_path):
    # Item 300's volume volB has title "PRONI Deeds Volume 25: 1689",
    # so estimated_date should be 1689-... regardless of metadata dates.
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(volume="volB"))
    r300 = next(r for r in results if r.isadg_id == 300)
    assert r300.estimated_date == "1689-01-01/1689-12-31"
    assert r300.estimated_source == "volume"


def _people_db(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    # two people on one page; link the page to an item
    db.upsert_names("100", "a.jpg",
                    [PersonRow("William Young", ["Wm Young"]),
                     PersonRow("Thomas Young")],
                    fingerprint=("pages/100/a.jpg.names.json", 1.0, 10))
    db._conn.execute(
        "INSERT INTO item_page (isadg_id, root_id, page_key, role) VALUES (?, ?, ?, ?)",
        (42, "100", "a.jpg", "primary"))
    db.commit()
    return db


def test_people_search_maps_to_items(tmp_path):
    from vtextract.index.people import people_search
    db = _people_db(tmp_path)
    hits = people_search(db, "Young")
    canon = {h.canonical: h for h in hits}
    assert set(canon) == {"William Young", "Thomas Young"}
    assert canon["William Young"].items == [42]
    assert (canon["William Young"].root_id, canon["William Young"].page_key) == ("100", "a.jpg")
    db.close()


def test_people_search_empty_query(tmp_path):
    from vtextract.index.people import people_search
    db = _people_db(tmp_path)
    assert people_search(db, "") == []
    db.close()


def test_person_only_narrows_to_items_on_that_page(tmp_path):
    from vtextract.index.models import PersonRow
    with _built(tmp_path) as db:
        db.upsert_names("volA", "volA_p1.jpg",
                        [PersonRow("Sarah Doheny", ["S. Doheny"])],
                        fingerprint=("pages/volA/volA_p1.jpg.names.json", 1.0, 10))
        db.commit()
        results = search(db, SearchQuery(person="Doheny"))
    ids = sorted(r.isadg_id for r in results)
    assert ids == [100, 200]  # both items reference volA_p1.jpg, where Doheny appears


def test_person_plus_text_is_intersection(tmp_path):
    from vtextract.index.models import PersonRow
    with _built(tmp_path) as db:
        db.upsert_names("volA", "volA_p1.jpg",
                        [PersonRow("Sarah Doheny")],
                        fingerprint=("pages/volA/volA_p1.jpg.names.json", 1.0, 10))
        db.commit()
        # person -> {100, 200}; text "Cork" -> {200}; intersection -> {200}
        results = search(db, SearchQuery(text="Cork", person="Doheny"))
    assert [r.isadg_id for r in results] == [200]


def test_unmatched_person_returns_empty(tmp_path):
    with _built(tmp_path) as db:
        results = search(db, SearchQuery(person="Zzznobody Absent"))
    assert results == []


def test_blank_person_leaves_results_unchanged(tmp_path):
    with _built(tmp_path) as db:
        baseline = [r.isadg_id for r in search(db, SearchQuery(text="Cork"))]
        withnone = [r.isadg_id for r in search(db, SearchQuery(text="Cork", person=None))]
    assert baseline == withnone == [200]
