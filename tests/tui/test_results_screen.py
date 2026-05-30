# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest
from textual.app import App

from vtextract.tui.bundle import Bundle
from vtextract.tui.screens.results import ResultsScreen


class _Harness(App):
    def __init__(self, results):
        super().__init__()
        self._results = results

    def compose(self):
        yield ResultsScreen(bundle=Bundle(), results=self._results, query="")

    def set_pane_count(self, _text):  # satisfies CountFooterMixin
        pass


@pytest.mark.asyncio
async def test_results_catalog_falls_back_to_estimated_date():
    # The catalog shows one Date column: the content date when present, else
    # the estimated date marked with square brackets (the ISAD(G) convention
    # for a supplied/estimated date).
    results = [
        {"isadg_id": 100, "content_date": "1737", "estimated_date": "1700/1799",
         "reference_code": "R1", "title": "Has a content date"},
        {"isadg_id": 521, "content_date": None,
         "estimated_date": "1776-01-01/1793-12-31",
         "reference_code": "", "title": "Estimated only"},
    ]
    async with _Harness(results).run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)
        headers = [str(c.label) for c in table.columns.values()]
        assert "Est." not in headers
        assert table.get_row_at(0)[2] == "1737"
        assert table.get_row_at(1)[2] == "[1776-01-01/1793-12-31]"


def test_results_screen_after_search(snap_compare, tmp_archive):
    from vtextract.tui.app import VtBrowseApp

    async def before(pilot):
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        for ch in "houston":
            await pilot.press(ch)
        await pilot.pause()
        await pilot.press("enter")  # submit search dialog
        await pilot.pause()
    assert snap_compare(VtBrowseApp(archive=tmp_archive), run_before=before)
