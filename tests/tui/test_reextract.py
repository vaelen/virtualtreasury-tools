# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Shift+P re-runs names extraction for the current page (using its notes)."""

from __future__ import annotations

import json
import subprocess

import pytest

from vtextract.names.models import NamesStats
from vtextract.tui.app import VtBrowseApp
from vtextract.tui.panes.people_pane import PeopleTable


async def _open_page(app, pilot, page_key="volA_p0.jpg"):
    await pilot.pause()
    app.open_transcription("volA", page_key, origin="pages")
    await pilot.pause()


async def _settle(pilot):
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def _fake_extract(archive_out, people):
    calls = []

    def extract(archive, **kw):
        calls.append(kw)
        # Behave like the real pass: write the sidecar the page would get.
        (archive / "pages" / "volA" / "volA_p0.jpg.names.json").write_text(
            json.dumps({"schema": 2, "model": kw["model"], "people": people}))
        return NamesStats(extracted=1, people=len(people))
    return extract, calls


@pytest.mark.asyncio
async def test_shift_p_reextracts_current_page_with_force(tmp_archive, monkeypatch):
    extract, calls = _fake_extract(tmp_archive, [["Daniel Power", "David Power Gent"]])
    monkeypatch.setattr("vtextract.names.extractor.extract", extract)
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("P")
        await _settle(pilot)
        messages = [n.message for n in app._notifications]
    assert calls and calls[0]["scope_pages"] == {("volA", "volA_p0.jpg")}
    assert calls[0]["force"] is True
    assert calls[0]["show_progress"] is False
    assert any("1 people" in m or "1 person" in m for m in messages), messages
    # the index was rebuilt so people search sees the new sidecar
    out = subprocess.run(["uv", "run", "vtindex", "people", "Daniel Power",
                          "--archive", str(tmp_archive), "--json"],
                         capture_output=True, text=True, check=True)
    assert "volA_p0.jpg" in out.stdout


@pytest.mark.asyncio
async def test_shift_p_refreshes_open_people_table(tmp_archive, monkeypatch):
    import asyncio
    monkeypatch.setattr(PeopleTable, "POLL_SECONDS", 0.05)
    (tmp_archive / "pages/volA/volA_p0.jpg.names.json").write_text(
        json.dumps({"schema": 2, "model": "m", "people": [["Old Name"]]}))
    subprocess.run(["uv", "run", "vtindex", "build", "--archive", str(tmp_archive)],
                   capture_output=True, check=True)
    extract, _ = _fake_extract(tmp_archive, [["New Name", "N. Name"]])
    monkeypatch.setattr("vtextract.names.extractor.extract", extract)
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("p")
        await pilot.pause()
        assert str(app.query_one(PeopleTable).get_row_at(0)[0]) == "Old Name"
        app.query_one("#transcription-body").parent.focus()
        await pilot.press("P")
        await _settle(pilot)
        await asyncio.sleep(0.2)  # the table's sidecar poll picks up the rewrite
        await pilot.pause()
        table = app.query_one(PeopleTable)
        assert [str(c) for c in table.get_row_at(0)] == ["New Name", "N. Name"]


@pytest.mark.asyncio
async def test_shift_p_failure_is_reported(tmp_archive, monkeypatch):
    def boom(archive, **kw):
        raise RuntimeError("model down")
    monkeypatch.setattr("vtextract.names.extractor.extract", boom)
    app = VtBrowseApp(archive=tmp_archive)
    async with app.run_test() as pilot:
        await _open_page(app, pilot)
        await pilot.press("P")
        await _settle(pilot)
        messages = [n.message for n in app._notifications]
    assert any("model down" in m for m in messages), messages
