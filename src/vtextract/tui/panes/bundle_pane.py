# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Tree

from vtextract.tui.bundle import Bundle, PageRef


class BundlePane(Tree[object]):
    """The left-hand pane that renders the user's current bundle.

    ``Tree[object]`` because leaf nodes carry a :class:`PageRef` while volume
    header nodes carry the bare ``root_id`` string.
    """

    DEFAULT_CSS = "BundlePane { width: 22; border: solid $accent; }"
    BINDINGS = [Binding("space", "remove_focused", "remove")]

    def __init__(self, bundle: Bundle) -> None:
        super().__init__("Bundle")
        self.bundle = bundle
        self.border_title = "Bundle"

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        self.clear()
        pages = self.bundle.effective_pages()
        if not pages:
            self.root.label = "(no selections)"
            return
        self.root.label = f"Bundle ({len(pages)})"
        self.root.expand()
        by_vol: dict[str, list[PageRef]] = {}
        for p in pages:
            by_vol.setdefault(p.root_id, []).append(p)
        for root_id, group in sorted(by_vol.items()):
            node = self.root.add(root_id, expand=True, data=root_id)
            for p in group:
                node.add_leaf(f"p.{p.page_key[:14]}", data=p)

    # ---------- keyboard handlers ----------

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """⏎ on a page leaf jumps the document pane to that page."""
        data = event.node.data
        if isinstance(data, PageRef):
            self.app.open_transcription(  # type: ignore[attr-defined]
                data.root_id, data.page_key,
            )

    def action_remove_focused(self) -> None:
        """`space` removes the focused page (or volume's pages) from bundle."""
        node = self.cursor_node
        if node is None:
            return
        data = node.data
        if isinstance(data, PageRef):
            if self.bundle.is_in_bundle(data):
                self.bundle.toggle_page(data)
        elif isinstance(data, str):
            for p in list(self.bundle.effective_pages()):
                if p.root_id == data and self.bundle.is_in_bundle(p):
                    self.bundle.toggle_page(p)
        else:
            return
        self.app.bundle_changed()  # type: ignore[attr-defined]
