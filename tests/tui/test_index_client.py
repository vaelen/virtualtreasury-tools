# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vtextract.index.models import IndexStats, ItemDetail, PageNav, SearchHit, VolumeInfo
from vtextract.tui.index_client import IndexClient, IndexError
from vtextract.tui.progress_events import DoneEvent, ProgressUpdate, StartEvent

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "archive"


@pytest.fixture
def built(tmp_path):
    """A fixture archive with its index built in-process."""
    from vtextract.index.service import IndexService
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    IndexService.build(archive)
    return archive


@pytest.fixture
def unbuilt(tmp_path):
    archive = tmp_path / "archive"
    shutil.copytree(FIXTURE, archive)
    return archive


@pytest.mark.asyncio
async def test_volumes_returns_volume_infos(built):
    client = IndexClient(built)
    try:
        vols = await client.volumes()
    finally:
        client.close()
    assert isinstance(vols[0], VolumeInfo)
    assert sorted(v.root_id for v in vols) == ["volA", "volB"]


@pytest.mark.asyncio
async def test_search_returns_hits(built):
    client = IndexClient(built)
    try:
        hits = await client.search(query="Houston", fields=("title",), limit=0)
    finally:
        client.close()
    assert hits and isinstance(hits[0], SearchHit)
    assert hits[0].isadg_id == 100


@pytest.mark.asyncio
async def test_page_and_pages_and_item(built):
    client = IndexClient(built)
    try:
        nav = await client.page("volA", "volA_p1.jpg")
        pages = await client.pages("volA")
        item = await client.item(100)
    finally:
        client.close()
    assert isinstance(nav, PageNav) and nav.previous.page_key == "volA_p0.jpg"
    assert [p.page_key for p in pages] == ["volA_p0.jpg", "volA_p1.jpg"]
    assert isinstance(item, ItemDetail) and item.isadg_id == 100


@pytest.mark.asyncio
async def test_stats_returns_index_stats(built):
    client = IndexClient(built)
    try:
        stats = await client.stats()
    finally:
        client.close()
    assert isinstance(stats, IndexStats)
    assert stats.items == 3


@pytest.mark.asyncio
async def test_stats_raises_index_error_when_missing(unbuilt):
    client = IndexClient(unbuilt)
    try:
        with pytest.raises(IndexError):
            await client.stats()
    finally:
        client.close()


@pytest.mark.asyncio
async def test_build_stream_emits_events_then_index_is_usable(unbuilt):
    client = IndexClient(unbuilt)
    try:
        events = [ev async for ev in client.build_stream()]
        assert isinstance(events[0], StartEvent)
        assert any(isinstance(e, ProgressUpdate) for e in events)
        assert isinstance(events[-1], DoneEvent)
        stats = await client.stats()
        assert stats.items == 3
    finally:
        client.close()


@pytest.mark.asyncio
async def test_search_person_narrows_results(built):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    # add a person onto a page the fixture items reference, in the built index
    db = IndexDB(built / "index" / "vtindex.sqlite3")
    db.upsert_names("volA", "volA_p1.jpg", [PersonRow("Sarah Doheny")],
                    fingerprint=("pages/volA/volA_p1.jpg.names.json", 1.0, 10))
    db.commit()
    db.close()

    client = IndexClient(built)
    try:
        person_only = await client.search(person="Doheny", limit=0)
        combined = await client.search(query="Cork", person="Doheny", limit=0)
    finally:
        client.close()
    assert sorted(h.isadg_id for h in person_only) == [100, 200]
    assert [h.isadg_id for h in combined] == [200]  # {100,200} ∩ {200}
