# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

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


def test_result_dtos_construct_with_defaults():
    from vtextract.index.models import (
        IndexStats, ItemDetail, PageEntry, PageNav, SearchHit, VolumeHeader,
    )
    e = PageEntry(root_id="volA", page_key="p.jpg")
    assert e.ordinal is None and e.label is None and e.role is None
    assert e.image is None and e.metadata is None and e.transcription is None

    nav = PageNav(volume=VolumeHeader(root_id="volA", title="T"),
                  previous=None, current=e, next=None)
    assert nav.current is e and nav.volume.title == "T"

    hit = SearchHit(
        isadg_id=1, title="t", reference_code="R", repository=None,
        content_date=None, created_date=None, estimated_date=None,
        estimated_source=None, matched_fields=[], matched_pages=[e],
        score=0.0, path="items/1",
    )
    assert hit.matched_pages == [e]

    detail = ItemDetail(
        isadg_id=1, reference_code="R", title="t", description="d",
        repository=None, content_begin=None, content_end=None,
        created_begin=None, created_end=None, estimated_begin=None,
        estimated_end=None, estimated_source=None, pages=[e],
    )
    assert detail.pages == [e]

    stats = IndexStats(items=3, volumes=2, pages=9, schema_version="3", stale=False)
    assert stats.items == 3 and stats.stale is False
