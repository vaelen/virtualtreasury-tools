# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
import pytest

from vtextract.index.models import (
    IndexStats, ItemDetail, PageEntry, PageNav, SearchHit, SearchQuery, VolumeInfo,
)
from vtextract.index.service import IndexService, IndexUnavailable


# built_archive / built_archive_with_search_hit come from tests/index/conftest.py
# (returns {"path", "root_id": "volA", "isadg_id": 100, ["query"]}).


def test_open_missing_index_raises_unavailable(tmp_path):
    with pytest.raises(IndexUnavailable, match="build"):
        IndexService(tmp_path / "archive")


def test_volumes_returns_volume_infos(built_archive):
    with IndexService(built_archive["path"]) as svc:
        vols = svc.volumes()
    roots = sorted(v.root_id for v in vols)
    assert isinstance(vols[0], VolumeInfo)
    assert roots == ["volA", "volB"]


def test_search_returns_hits_with_enriched_pages(built_archive_with_search_hit):
    info = built_archive_with_search_hit
    with IndexService(info["path"]) as svc:
        hits = svc.search(SearchQuery(text=info["query"], fields=("transcription",), limit=0))
    assert hits and isinstance(hits[0], SearchHit)
    hit = next(h for h in hits if h.isadg_id == info["isadg_id"])
    pg = next(p for p in hit.matched_pages if p.page_key == "volA_p1.jpg")
    assert isinstance(pg, PageEntry)
    assert pg.root_id == "volA"
    assert pg.role in ("primary", "context")
    assert pg.transcription and pg.transcription.endswith("volA_p1.jpg.txt")
    assert pg.image is None


def test_pages_returns_entries_in_order(built_archive):
    with IndexService(built_archive["path"]) as svc:
        pages = svc.pages("volA")
    assert [p.page_key for p in pages] == ["volA_p0.jpg", "volA_p1.jpg"]
    assert pages[0].ordinal == 1


def test_page_nav_mid_volume(built_archive):
    with IndexService(built_archive["path"]) as svc:
        nav = svc.page("volA", "volA_p1.jpg")
    assert isinstance(nav, PageNav)
    assert nav.current.page_key == "volA_p1.jpg"
    assert nav.current.ordinal == 2
    assert nav.previous.page_key == "volA_p0.jpg"
    assert nav.next is None
    assert nav.volume.title == "Registry of Deeds Transcript Book 86: memorials 1737"


def test_page_unknown_returns_none(built_archive):
    with IndexService(built_archive["path"]) as svc:
        assert svc.page("volA", "nope.jpg") is None


def test_item_returns_detail(built_archive):
    with IndexService(built_archive["path"]) as svc:
        item = svc.item(built_archive["isadg_id"])
    assert isinstance(item, ItemDetail)
    assert item.isadg_id == built_archive["isadg_id"]
    assert all(isinstance(p, PageEntry) and p.role for p in item.pages)
    # item pages are link-only: file paths are intentionally not resolved.
    assert all(p.transcription is None and p.image is None for p in item.pages)


def test_item_unknown_returns_none(built_archive):
    with IndexService(built_archive["path"]) as svc:
        assert svc.item(99999) is None


def test_stats(built_archive):
    with IndexService(built_archive["path"]) as svc:
        stats = svc.stats()
    assert isinstance(stats, IndexStats)
    assert stats.items == 3
    assert stats.stale is False


def test_is_stale_false_after_build(built_archive):
    with IndexService(built_archive["path"]) as svc:
        assert svc.is_stale() is False


def test_build_then_reopen_reflects_new_item(built_archive):
    archive = built_archive["path"]
    svc = IndexService(archive)
    try:
        before = svc.stats().items
        # Add a genuinely new item (distinct isadgID) so the count grows.
        data = json.loads((archive / "items" / "300" / "metadata.json").read_text())
        data["isadgID"] = 400
        (archive / "items" / "400").mkdir()
        (archive / "items" / "400" / "metadata.json").write_text(json.dumps(data))
        IndexService.build(archive)
        svc.reopen()
        assert svc.stats().items == before + 1
    finally:
        svc.close()


def test_service_people(tmp_path):
    from vtextract.index.builder import build
    from vtextract.index.service import IndexService
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "a.jpg.names.json").write_text(
        '{"schema":2,"model":"m","people":[["William Young","Wm Young"]]}'
    )
    build(tmp_path)
    with IndexService(tmp_path) as svc:
        hits = svc.people("Young")
    assert hits[0].canonical == "William Young"
