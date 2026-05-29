# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from textual.widgets import Static

from vtextract.tui.bundle import Bundle


class BundlePane(Static):
    DEFAULT_CSS = "BundlePane { width: 22; border: solid $accent; }"

    def __init__(self, bundle: Bundle) -> None:
        super().__init__()
        self.bundle = bundle
        self.border_title = "Bundle"

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        pages = self.bundle.effective_pages()
        if not pages:
            self.update("(no selections)")
            return
        # Grouped-by-volume rendering filled out in Task 15.
        self.update(f"{len(pages)} pages")
