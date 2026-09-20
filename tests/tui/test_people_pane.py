# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Viewing a page's names.json people in a read-only pane beside the page."""

from __future__ import annotations

import json
import subprocess

import pytest

from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.notes_pane import NotesEditor
from vtextract.tui.panes.people_pane import PeopleTable

SIDECAR = {"schema": 2, "model": "m",
           "people": [["William Young", "Wm Young", "Sgt. Young"], ["Patrick Kelly"]]}


def _write_names(archive, page_key="volA_p0.jpg"):
    (archive / "pages" / "volA" / f"{page_key}.names.json").write_text(json.dumps(SIDECAR))
    # A new sidecar makes the fixture's index stale, which would pop the rebuild
    # prompt on startup; rebuild so the app opens straight to the volumes list.
    subprocess.run(["uv", "run", "vtindex", "build", "--archive", str(archive)],
                   capture_output=True, check=True)


async def _open_page(app, pilot, page_key="volA_p0.jpg"):
    await pilot.pause()
    app.open_transcription("volA", page_key, origin="pages")
    await pilot.pause()


def _page(app):
    return app.query_one("#transcription-body").parent


@pytest.mark.asyncio
async def test_p_opens_people_table_and_p_closes(tmp_archive):
    _write_names(tmp_archive)
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        table = app.query_one(PeopleTable)
        assert app.focused is table
        rows = [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]
        assert rows == [["William Young", "Wm Young, Sgt. Young"], ["Patrick Kelly", ""]]
        _page(app).focus()
        await pilot.press("p")
        await pilot.pause()
        assert len(app.query(PeopleTable)) == 0
        assert app.focused is _page(app)


@pytest.mark.asyncio
async def test_escape_in_people_table_closes_it(tmp_archive):
    _write_names(tmp_archive)
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.query(PeopleTable)) == 0
        assert len(app.query("#transcription-body")) == 1  # still on the page


@pytest.mark.asyncio
async def test_p_without_names_file_shows_toast_and_no_pane(tmp_archive):
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        assert len(app.query(PeopleTable)) == 0
        messages = [n.message for n in app._notifications]
        assert len(messages) == 1 and "not been extracted" in messages[0]


@pytest.mark.asyncio
async def test_people_sits_below_notes_and_closes_independently(tmp_archive):
    _write_names(tmp_archive)
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("p")          # people first ...
        await pilot.pause()
        _page(app).focus()
        await pilot.press("n")          # ... then notes must still land on top
        await pilot.pause()
        sidebar = app.query_one(PeopleTable).parent
        assert sidebar is app.query_one(NotesEditor).parent
        assert [type(c) for c in sidebar.children] == [NotesEditor, PeopleTable]
        _page(app).focus()
        await pilot.press("p")          # close people, notes stays
        await pilot.pause()
        assert len(app.query(PeopleTable)) == 0
        assert len(app.query(NotesEditor)) == 1


@pytest.mark.asyncio
async def test_paging_away_drops_people_and_saves_notes(tmp_archive):
    _write_names(tmp_archive)
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("n")
        await pilot.pause()
        app.query_one(NotesEditor).text = "kept"
        _page(app).focus()
        await pilot.press("p")
        await pilot.pause()
        _page(app).focus()
        await pilot.press("right")
        await pilot.pause()
        assert len(app.query(PeopleTable)) == 0
        assert len(app.query(NotesEditor)) == 0
        assert (tmp_archive / "pages" / "volA" / "volA_p0.jpg.notes.md").read_text() == "kept"
