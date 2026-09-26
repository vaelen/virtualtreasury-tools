# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Escape from the transcription view returns to wherever it was opened from:
the search results when reached via a result row, the page list when reached
via a volume's page list."""

from __future__ import annotations

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.document_pane import DocumentPane
from vtextract.tui.screens.pages import PagesScreen
from vtextract.tui.screens.results import ResultsScreen
from vtextract.tui.screens.transcription import TranscriptionScreen


def _active(app):
    return app.query_one(DocumentPane).children[0]


@pytest.mark.asyncio
async def test_escape_from_transcription_returns_to_results(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        for ch in "houston":
            await pilot.press(ch)
        await pilot.pause()
        await pilot.press("enter")  # submit search -> ResultsScreen
        await pilot.pause()
        assert isinstance(_active(app), ResultsScreen)

        await pilot.press("enter")  # open first matched page's transcription
        await pilot.pause()
        assert isinstance(_active(app), TranscriptionScreen)

        await pilot.press("escape")  # should go BACK to the search results
        await pilot.pause()
        assert isinstance(_active(app), ResultsScreen), (
            f"escape from a results-opened page should return to results, "
            f"got {_active(app)!r}"
        )


@pytest.mark.asyncio
async def test_escape_from_transcription_via_pages_returns_to_pages(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")  # volumes -> open first volume's page list
        await pilot.pause()
        assert isinstance(_active(app), PagesScreen)

        await pilot.press("enter")  # open a page's transcription
        await pilot.pause()
        assert isinstance(_active(app), TranscriptionScreen)

        await pilot.press("escape")  # should go BACK to the page list
        await pilot.pause()
        assert isinstance(_active(app), PagesScreen), (
            f"escape from a page-list-opened page should return to the page "
            f"list, got {_active(app)!r}"
        )
