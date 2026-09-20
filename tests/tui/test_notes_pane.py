# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Editing a page's notes.md in a split pane beside the transcription."""

from __future__ import annotations

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.notes_pane import NotesEditor


def _notes(archive, page_key="volA_p0.jpg"):
    return archive / "pages" / "volA" / f"{page_key}.notes.md"


async def _open_page(app, pilot, page_key="volA_p0.jpg"):
    await pilot.pause()
    app.open_transcription("volA", page_key, origin="pages")
    await pilot.pause()


@pytest.mark.asyncio
async def test_n_opens_editor_with_existing_notes_and_n_closes(tmp_archive):
    _notes(tmp_archive).write_text("J. Smith is James Smith.\n")
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        assert len(app.query(NotesEditor)) == 0
        await pilot.press("n")
        await pilot.pause()
        editor = app.query_one(NotesEditor)
        assert editor.text == "J. Smith is James Smith.\n"
        assert app.focused is editor
        # transcription still shown alongside, and 'n' from it closes the pane
        assert len(app.query("#transcription-body")) == 1
        app.query_one("#transcription-body").parent.focus()
        await pilot.press("n")
        await pilot.pause()
        assert len(app.query(NotesEditor)) == 0


@pytest.mark.asyncio
async def test_escape_in_editor_closes_and_saves(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        app.query_one(NotesEditor).text = "Ormond is the estate."
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.query(NotesEditor)) == 0
        assert len(app.query("#transcription-body")) == 1  # still on the page
        assert _notes(tmp_archive).read_text() == "Ormond is the estate."


@pytest.mark.asyncio
async def test_whitespace_only_notes_delete_the_file(tmp_archive):
    _notes(tmp_archive).write_text("old notes")
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        app.query_one(NotesEditor).text = "  \n\t\n"
        await pilot.press("escape")
        await pilot.pause()
        assert not _notes(tmp_archive).exists()


@pytest.mark.asyncio
async def test_empty_editor_creates_no_file(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not _notes(tmp_archive).exists()


@pytest.mark.asyncio
async def test_paging_away_saves_open_notes(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        app.query_one(NotesEditor).text = "saved on page change"
        app.query_one("#transcription-body").parent.focus()
        await pilot.press("right")
        await pilot.pause()
        assert len(app.query(NotesEditor)) == 0
        assert _notes(tmp_archive).read_text() == "saved on page change"


@pytest.mark.asyncio
async def test_quitting_saves_open_notes(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        app.query_one(NotesEditor).text = "saved on quit"
        app.exit()
    assert _notes(tmp_archive).read_text() == "saved on quit"
