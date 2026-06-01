# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest
from textual.app import App

from vtextract.index.models import PageEntry, SearchHit
from vtextract.tui.bundle import Bundle, PageRef
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
        SearchHit(isadg_id=100, content_date="1737", estimated_date="1700/1799",
                  reference_code="R1", title="Has a content date",
                  repository=None, created_date=None, estimated_source=None,
                  matched_fields=[], matched_pages=[], score=1.0, path="items/100"),
        SearchHit(isadg_id=521, content_date=None,
                  estimated_date="1776-01-01/1793-12-31",
                  reference_code="", title="Estimated only",
                  repository=None, created_date=None, estimated_source=None,
                  matched_fields=[], matched_pages=[], score=1.0, path="items/521"),
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


class _ToggleHarness(App):
    def __init__(self, results, bundle):
        super().__init__()
        self._results = results
        self._bundle = bundle
        self.bundle_changed_calls = 0

    def compose(self):
        yield ResultsScreen(bundle=self._bundle, results=self._results, query="")

    def set_pane_count(self, _text):  # satisfies CountFooterMixin
        pass

    def bundle_changed(self):
        self.bundle_changed_calls += 1


_TOGGLE_RESULTS = [
    SearchHit(isadg_id=1, content_date="1700", estimated_date=None,
              reference_code="R1", title="One",
              repository=None, created_date=None, estimated_source=None,
              matched_fields=[], score=1.0, path="items/1",
              matched_pages=[PageEntry(root_id="V", page_key="p1")]),
    SearchHit(isadg_id=2, content_date="1701", estimated_date=None,
              reference_code="R2", title="Two",
              repository=None, created_date=None, estimated_source=None,
              matched_fields=[], score=1.0, path="items/2",
              matched_pages=[PageEntry(root_id="V", page_key="p2")]),
]


@pytest.mark.asyncio
async def test_selected_marker_renders_not_eaten_by_markup():
    """Regression: a selected row's marker must actually render. Textual feeds
    plain-str DataTable cells through Rich markup (``Text.from_markup``), which
    parses ``[x]`` as a style tag and renders nothing — the box vanished. The
    marker must survive the render path, not merely be stored."""
    from textual.widgets._data_table import default_cell_formatter

    bundle = Bundle()
    harness = _ToggleHarness(_TOGGLE_RESULTS, bundle)
    async with harness.run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)
        # what DataTable actually displays for row 0's selection cell:
        assert default_cell_formatter(table.get_cell_at((0, 0))).plain == "[ ]"
        await pilot.press("a")  # select all
        assert default_cell_formatter(table.get_cell_at((0, 0))).plain == "[x]"


@pytest.mark.asyncio
async def test_results_a_selects_all_then_deselects_all():
    bundle = Bundle()
    harness = _ToggleHarness(_TOGGLE_RESULTS, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # nothing selected -> select all
        assert set(bundle.selected_items) == {1, 2}
        table = pilot.app.query_one(ResultsScreen)
        assert str(table.get_row_at(0)[0]) == "[x]"
        assert str(table.get_row_at(1)[0]) == "[x]"

        await pilot.press("a")  # all selected -> deselect all
        assert bundle.selected_items == {}
        assert str(table.get_row_at(0)[0]) == "[ ]"
        assert str(table.get_row_at(1)[0]) == "[ ]"
        assert harness.bundle_changed_calls == 2


@pytest.mark.asyncio
async def test_results_a_from_partial_selects_all():
    bundle = Bundle()
    bundle.toggle_item(1, [PageRef("V", "p1")])  # only id 1 selected
    harness = _ToggleHarness(_TOGGLE_RESULTS, bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")  # partial -> select all (not deselect)
        assert set(bundle.selected_items) == {1, 2}


@pytest.mark.asyncio
async def test_results_a_on_empty_is_noop():
    bundle = Bundle()
    harness = _ToggleHarness([], bundle)
    async with harness.run_test() as pilot:
        await pilot.press("a")
        assert bundle.selected_items == {}
        assert harness.bundle_changed_calls == 0
