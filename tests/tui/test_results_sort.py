# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Sort logic for the results screen: relevance + date asc/desc, undated last."""

from __future__ import annotations

from types import SimpleNamespace

from vtextract.tui.screens.results import SortMode, sort_results


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
