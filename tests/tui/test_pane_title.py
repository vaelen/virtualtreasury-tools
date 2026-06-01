# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""The document pane's border title reflects what it's showing, and its
bottom border carries a viewport count for list screens."""

from __future__ import annotations

import re

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.document_pane import DocumentPane

_COUNT = re.compile(r"^(0 of 0|\d+-\d+ of \d+)$")


@pytest.mark.asyncio
async def test_volumes_title_and_count(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        pane = app.query_one(DocumentPane)
        assert pane.border_title == "Volumes"
        assert _COUNT.match(str(pane.border_subtitle or ""))


@pytest.mark.asyncio
async def test_pages_title_is_volume_title(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        # First volume's title from the table, then drill in.
        volumes = app.query_one("VolumesScreen")
        expected = volumes._row_titles[0]
        await pilot.press("enter")
        await pilot.pause()
        pane = app.query_one(DocumentPane)
        assert pane.border_title == expected
        assert _COUNT.match(str(pane.border_subtitle or ""))


@pytest.mark.asyncio
async def test_pages_title_survives_escape_from_transcription(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        expected = app.query_one("VolumesScreen")._row_titles[0]
        await pilot.press("enter")   # volume -> pages
        await pilot.pause()
        await pilot.press("enter")   # page -> transcription
        await pilot.pause()
        await pilot.press("escape")  # back to pages
        await pilot.pause()
        pane = app.query_one(DocumentPane)
        assert pane.border_title == expected


@pytest.mark.asyncio
async def test_results_title_is_search_results(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        for ch in "houston":
            await pilot.press(ch)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        pane = app.query_one(DocumentPane)
        assert pane.border_title == "Search Results · sort: relevance"
        assert _COUNT.match(str(pane.border_subtitle or ""))
