# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Sort logic for the results screen: relevance + date asc/desc, undated last."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.app import App

from vtextract.index.models import SearchHit
from vtextract.tui.bundle import Bundle
from vtextract.tui.screens.results import ResultsScreen, SortMode, sort_results


def _hit(isadg_id, score, content_date=None, estimated_date=None):
    # sort_results is duck-typed: it only reads these four attributes.
    return SimpleNamespace(
        isadg_id=isadg_id, score=score,
        content_date=content_date, estimated_date=estimated_date,
    )


def _ids(results):
    return [r.isadg_id for r in results]


def test_sortmode_next_wraps_through_three_states():
    assert SortMode.RELEVANCE.next() is SortMode.DATE_ASC
    assert SortMode.DATE_ASC.next() is SortMode.DATE_DESC
    assert SortMode.DATE_DESC.next() is SortMode.RELEVANCE


def test_relevance_orders_best_bm25_first():
    # bm25: more-negative = better, so it must sort ascending by score.
    hits = [_hit(1, -1.0), _hit(2, -5.0), _hit(3, -3.0)]
    assert _ids(sort_results(hits, SortMode.RELEVANCE)) == [2, 3, 1]


def test_relevance_is_stable_for_ties():
    hits = [_hit(1, 0.0), _hit(2, 0.0), _hit(3, 0.0)]
    assert _ids(sort_results(hits, SortMode.RELEVANCE)) == [1, 2, 3]


def test_date_ascending_oldest_first_undated_last():
    hits = [
        _hit(1, -5.0, content_date="1850"),
        _hit(2, -1.0, content_date="1700"),
        _hit(3, -3.0),  # undated
    ]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [2, 1, 3]


def test_date_descending_newest_first_undated_still_last():
    hits = [
        _hit(1, -5.0, content_date="1850"),
        _hit(2, -1.0, content_date="1700"),
        _hit(3, -3.0),  # undated
    ]
    assert _ids(sort_results(hits, SortMode.DATE_DESC)) == [1, 2, 3]


def test_estimated_date_used_when_content_date_missing():
    # content_date or estimated_date — same rule the Date column displays.
    hits = [
        _hit(1, 0.0, content_date="1900"),
        _hit(2, 0.0, estimated_date="1800"),
    ]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [2, 1]


def test_date_ranges_compare_lexicographically():
    hits = [
        _hit(1, 0.0, content_date="1798/1799"),
        _hit(2, 0.0, content_date="1700"),
    ]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [2, 1]


def test_equal_dates_keep_isadg_ascending_in_both_directions():
    hits = [_hit(3, 0.0, content_date="1700"), _hit(1, 0.0, content_date="1700")]
    assert _ids(sort_results(hits, SortMode.DATE_ASC)) == [1, 3]
    assert _ids(sort_results(hits, SortMode.DATE_DESC)) == [1, 3]


def test_mode_labels_for_title():
    assert SortMode.RELEVANCE.value == "relevance"
    assert SortMode.DATE_ASC.value == "date ↑"
    assert SortMode.DATE_DESC.value == "date ↓"


class _SortHarness(App):
    def __init__(self, results):
        super().__init__()
        self._results = results
        self.pane_title = None

    def compose(self):
        yield ResultsScreen(bundle=Bundle(), results=self._results, query="")

    def set_pane_count(self, _text):  # satisfies CountFooterMixin
        pass

    def set_pane_title(self, text):  # satisfies _update_title
        self.pane_title = text


def _make_hit(isadg_id, score, content_date=None):
    return SearchHit(
        isadg_id=isadg_id, title=f"R{isadg_id}", reference_code=f"R{isadg_id}",
        repository=None, content_date=content_date, created_date=None,
        estimated_date=None, estimated_source=None, matched_fields=[],
        matched_pages=[], score=score, path=f"items/{isadg_id}",
    )


# Relevance: by score asc -> [1, 3, 2]; Date asc: [2, 1, 3] (id 3 undated last);
# Date desc: [1, 2, 3] (undated still last).
_SORT_RESULTS = [
    _make_hit(1, -5.0, content_date="1850"),
    _make_hit(2, -1.0, content_date="1700"),
    _make_hit(3, -3.0, content_date=None),
]


def _row_ids(table):
    return [int(table.get_row_at(i)[1]) for i in range(table.row_count)]


@pytest.mark.asyncio
async def test_d_cycles_sort_order_and_title_and_wraps():
    async with _SortHarness(list(_SORT_RESULTS)).run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)

        # default: relevance
        assert _row_ids(table) == [1, 3, 2]
        assert pilot.app.pane_title == "Search Results · sort: relevance"

        await pilot.press("d")  # -> date ascending
        assert _row_ids(table) == [2, 1, 3]
        assert pilot.app.pane_title == "Search Results · sort: date ↑"

        await pilot.press("d")  # -> date descending
        assert _row_ids(table) == [1, 2, 3]
        assert pilot.app.pane_title == "Search Results · sort: date ↓"

        await pilot.press("d")  # wraps -> relevance
        assert _row_ids(table) == [1, 3, 2]
        assert pilot.app.pane_title == "Search Results · sort: relevance"


@pytest.mark.asyncio
async def test_d_keeps_cursor_on_same_result():
    async with _SortHarness(list(_SORT_RESULTS)).run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)
        table.move_cursor(row=2)  # relevance order row 2 == id 2
        assert int(table.get_row_at(table.cursor_row)[1]) == 2
        await pilot.press("d")  # date asc: id 2 is now row 0
        assert int(table.get_row_at(table.cursor_row)[1]) == 2


@pytest.mark.asyncio
async def test_d_on_empty_results_is_noop():
    async with _SortHarness([]).run_test() as pilot:
        table = pilot.app.query_one(ResultsScreen)
        await pilot.press("d")
        assert table.row_count == 0
        # mode did not advance; title still default
        assert pilot.app.pane_title == "Search Results · sort: relevance"
