# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Mixin that publishes a viewport row count into the document pane footer.

Mix into a ``DataTable`` screen, call ``_wire_count_footer()`` once from
``on_mount`` (after the initial rows are added), and the pane's bottom border
shows ``"<first>-<last> of <total>"`` kept in sync with scroll and resize.
The range maths lives in the pure ``viewport`` module."""

from __future__ import annotations

from textual import events

from vtextract.tui.viewport import format_count, viewport_range


class CountFooterMixin:
    def _wire_count_footer(self) -> None:
        # Re-publish on every vertical scroll, and once after first layout.
        # ``on_resize`` (below) covers the final layout pass, when the table
        # reaches its allotted size — call_after_refresh alone fires too early.
        self.watch(self, "scroll_y", self._publish_count, init=False)
        self.call_after_refresh(self._publish_count)

    def _visible_rows(self) -> int:
        # scrollable_content_region spans the whole DataTable body; the column
        # header is painted as a fixed row on top of it, so discount it.
        height = self.scrollable_content_region.height
        if getattr(self, "show_header", False):
            height -= self.header_height
        return max(height, 0)

    def _publish_count(self) -> None:
        total = self.row_count
        first, last = viewport_range(
            float(self.scroll_y), self._visible_rows(), total
        )
        self.app.set_pane_count(format_count(first, last, total))  # type: ignore[attr-defined]

    def on_resize(self, _: events.Resize) -> None:
        # DataTable/ScrollView resize via the private _on_resize hook, so this
        # public handler is dispatched alongside it without shadowing layout.
        self._publish_count()
