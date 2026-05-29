# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.index.models import (
    BuildStats,
    ItemRow,
    PageLink,
    SearchQuery,
    SearchResult,
    VolumeInfo,
    VolumeRow,
)


def test_item_row_defaults():
    row = ItemRow(isadg_id=1, reference_code="R", title="T", description="D", repository="Repo")
    assert row.content_begin is None and row.created_end is None
    assert row.volumes == [] and row.pages == []
    assert row.path == "items/1"


def test_search_query_defaults():
    q = SearchQuery()
    assert q.text is None
    assert q.fields == ("title", "description", "transcription")
    assert q.date_type == "content"
    assert q.limit == 50
    assert q.volume is None


def test_build_stats_total():
    s = BuildStats(added=2, updated=1, removed=0, unchanged=5, skipped=1)
    # processed = files looked at this build = added + updated + unchanged + skipped
    assert s.processed == 9


def test_search_result_roundtrip_fields():
    r = SearchResult(
        isadg_id=1, title="T", reference_code="R", repository="Repo",
        content_date="1737-05-06", created_date=None,
        matched_fields=["title"], matched_pages=[("208925", "p.jpg", "primary")],
        score=1.5, path="items/1",
    )
    assert r.matched_pages == [("208925", "p.jpg", "primary")]
