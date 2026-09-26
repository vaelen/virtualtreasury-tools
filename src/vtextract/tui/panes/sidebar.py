# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from textual.containers import Vertical
from textual.widget import Widget


class Sidebar(Vertical):
    """Right-hand column beside the page view: notes on top, people below.

    Mounted into the DocumentPane on demand and removed once its last child
    closes, so the page view gets the full width back.
    """

    DEFAULT_CSS = """
    Sidebar { width: 1fr; }
    Sidebar > * { height: 1fr; }
    """

    @classmethod
    async def open(cls, pane: Widget, child: Widget, *, on_top: bool = False) -> None:
        """Mount ``child`` into ``pane``'s sidebar, creating the sidebar if needed."""
        bars = pane.query(cls)
        if bars:
            bar = bars.first()
        else:
            bar = cls()
            await pane.mount(bar)
        if on_top and bar.children:
            await bar.mount(child, before=0)
        else:
            await bar.mount(child)

    @staticmethod
    def close(child: Widget) -> None:
        """Remove ``child``; drop the sidebar too if it was the last one."""
        bar = child.parent
        child.remove()
        if bar is not None and len(bar.children) == 1:
            bar.remove()
