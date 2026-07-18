# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Reopening the search results (esc from a document, or the global ``r``)
restores the list position and sort order the user left, instead of jumping
back to the top. A new search still starts at the top in relevance order."""

from __future__ import annotations

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.document_pane import DocumentPane
from vtextract.tui.screens.results import ResultsScreen, SortMode
from vtextract.tui.screens.transcription import TranscriptionScreen


def _active(app):
    return app.query_one(DocumentPane).children[0]


async def _search_houston(pilot):
    """Run the fixture search that yields two results (items 100 and 200)."""
    await pilot.press("f")
    await pilot.pause()
    for ch in "houston":
        await pilot.press(ch)
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.asyncio
async def test_escape_restores_results_position_and_sort(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _search_houston(pilot)
        results = _active(app)
        assert isinstance(results, ResultsScreen)
        assert results.row_count == 2

        await pilot.press("d")     # relevance -> date ascending
        await pilot.press("down")  # move to the second row
        await pilot.pause()
        assert results.cursor_row == 1
        row_id = results.results[1].isadg_id

        await pilot.press("enter")  # open that result's transcription
        await pilot.pause()
        assert isinstance(_active(app), TranscriptionScreen)

        await pilot.press("escape")  # back to results
        await pilot.pause()
        results = _active(app)
        assert isinstance(results, ResultsScreen)
        assert results.sort_mode is SortMode.DATE_ASC
        assert results.cursor_row == 1
        assert results.results[results.cursor_row].isadg_id == row_id


@pytest.mark.asyncio
async def test_new_search_resets_results_position(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _search_houston(pilot)
        await pilot.press("d")     # change the sort
        await pilot.press("down")  # and the position
        await pilot.pause()

        await _search_houston(pilot)  # a fresh search starts at the top
        results = _active(app)
        assert isinstance(results, ResultsScreen)
        assert results.sort_mode is SortMode.RELEVANCE
        assert results.cursor_row == 0
