# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Reopening a volume's page list (esc from a document) restores the row the
user was on. Opening a different volume still starts at the top."""

from __future__ import annotations

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.document_pane import DocumentPane
from vtextract.tui.screens.pages import PagesScreen
from vtextract.tui.screens.transcription import TranscriptionScreen


def _active(app):
    return app.query_one(DocumentPane).children[0]


@pytest.mark.asyncio
async def test_escape_restores_pages_position(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")  # volumes -> first volume's page list (volA)
        await pilot.pause()
        pages = _active(app)
        assert isinstance(pages, PagesScreen)
        assert pages.row_count == 2

        await pilot.press("down")   # move to the second page
        await pilot.pause()
        assert pages.cursor_row == 1

        await pilot.press("enter")  # open its transcription
        await pilot.pause()
        assert isinstance(_active(app), TranscriptionScreen)

        await pilot.press("escape")  # back to the page list
        await pilot.pause()
        pages = _active(app)
        assert isinstance(pages, PagesScreen)
        assert pages.cursor_row == 1


@pytest.mark.asyncio
async def test_other_volume_starts_at_top(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await pilot.pause()
        # A remembered position in another volume must not leak into this one.
        app.last_pages_root = "volB"
        app.last_pages_row = 1
        app.open_pages("volA")
        await pilot.pause()
        pages = _active(app)
        assert isinstance(pages, PagesScreen)
        assert pages.cursor_row == 0
