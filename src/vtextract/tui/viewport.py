# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Pure viewport-range maths for the document pane's count footer.

No Textual imports — the widget layer (``count_footer.CountFooterMixin``)
feeds these the live scroll offset / viewport height / row count and renders
the result into the pane's ``border_subtitle``."""

from __future__ import annotations


def viewport_range(scroll_y: float, viewport_height: int, total: int) -> tuple[int, int]:
    """1-based (first, last) row numbers currently visible, given the vertical
    scroll offset (in rows), how many rows fit, and the total row count.

    Returns ``(0, 0)`` when there is nothing to show (no rows or no height).
    """
    if total <= 0 or viewport_height <= 0:
        return (0, 0)
    first = int(scroll_y) + 1
    first = max(1, min(first, total))
    last = min(first + viewport_height - 1, total)
    return (first, last)


def format_count(first: int, last: int, total: int) -> str:
    """Render a range as ``"12-36 of 100"``; ``"0 of 0"`` when empty."""
    if total <= 0:
        return "0 of 0"
    return f"{first}-{last} of {total}"
