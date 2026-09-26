# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Pure viewport-range maths backing the pane count footer."""

from __future__ import annotations

from vtextract.tui.viewport import format_count, viewport_range


def test_empty_total_is_zero_range():
    assert viewport_range(0.0, 25, 0) == (0, 0)


def test_zero_viewport_height_is_zero_range():
    assert viewport_range(0.0, 0, 100) == (0, 0)


def test_all_rows_fit():
    assert viewport_range(0.0, 25, 3) == (1, 3)


def test_scrolled_into_middle():
    # 25 rows visible starting at content offset 11 → 1-based rows 12..36.
    assert viewport_range(11.0, 25, 100) == (12, 36)


def test_scrolled_to_end_clamps_last_to_total():
    assert viewport_range(90.0, 25, 100) == (91, 100)


def test_scroll_past_end_clamps_first_to_total():
    assert viewport_range(200.0, 25, 100) == (100, 100)


def test_fractional_scroll_floors_to_row():
    assert viewport_range(11.7, 10, 100) == (12, 21)


def test_format_empty():
    assert format_count(0, 0, 0) == "0 of 0"


def test_format_all_fit():
    assert format_count(1, 3, 3) == "1-3 of 3"


def test_format_scrolled():
    assert format_count(12, 36, 100) == "12-36 of 100"
