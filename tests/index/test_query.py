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
    assert ("volA", "volA_p1.jpg") in r100.matched_pages
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
