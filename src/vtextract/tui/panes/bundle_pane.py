# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.widgets import Tree

from vtextract.tui.bundle import Bundle


class BundlePane(Tree[str]):
    DEFAULT_CSS = "BundlePane { width: 22; border: solid $accent; }"

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
        by_vol: dict[str, list] = {}
        for p in pages:
            by_vol.setdefault(p.root_id, []).append(p)
        for root_id, group in sorted(by_vol.items()):
            node = self.root.add(root_id, expand=True)
            for p in group:
                node.add_leaf(f"p.{p.page_key[:14]}")
