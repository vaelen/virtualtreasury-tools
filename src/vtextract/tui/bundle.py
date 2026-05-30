# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""The vtbrowse selection model.

Three components, derived effective bundle. See
docs/superpowers/specs/2026-05-29-vtbrowse-tui-design.md §Selection model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Literal

PageState = Literal["include", "exclude"]
BUNDLE_VERSION = 1


@dataclass(frozen=True, order=True)
class PageRef:
    root_id: str
    page_key: str


@dataclass
class Bundle:
    selected_items: dict[int, list[PageRef]] = field(default_factory=dict)
    page_state: dict[PageRef, PageState] = field(default_factory=dict)

    # ----- queries -----

    def is_in_bundle(self, page: PageRef) -> bool:
        if self.page_state.get(page) == "exclude":
            return False
        if self.page_state.get(page) == "include":
            return True
        return any(page in pages for pages in self.selected_items.values())

    def effective_pages(self) -> list[PageRef]:
        seen: set[PageRef] = set()
        for pages in self.selected_items.values():
            seen.update(pages)
        seen.update(p for p, s in self.page_state.items() if s == "include")
        seen.difference_update(p for p, s in self.page_state.items() if s == "exclude")
        return sorted(seen)

    # ----- mutations -----

    def toggle_item(self, isadg_id: int, matched_pages: Iterable[PageRef]) -> None:
        if isadg_id in self.selected_items:
            del self.selected_items[isadg_id]
        else:
            self.selected_items[isadg_id] = list(matched_pages)

    def toggle_page(self, page: PageRef) -> None:
        if self.is_in_bundle(page):
            self.page_state[page] = "exclude"
        else:
            self.page_state[page] = "include"

    def clear_page_override(self, page: PageRef) -> None:
        self.page_state.pop(page, None)

    def replace_contents(self, other: "Bundle") -> None:
        """Adopt ``other``'s selections in place, keeping this instance's
        identity so live holders (e.g. the BundlePane) observe the change."""
        self.selected_items = other.selected_items
        self.page_state = other.page_state

    # ----- persistence -----

    def to_json(self) -> str:
        return json.dumps({
            "version": BUNDLE_VERSION,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "selected_items": [
                {"isadg_id": k,
                 "matched_pages": [{"root_id": p.root_id, "page_key": p.page_key}
                                   for p in v]}
                for k, v in sorted(self.selected_items.items())
            ],
            "page_state": [
                {"root_id": p.root_id, "page_key": p.page_key, "state": s}
                for p, s in sorted(self.page_state.items())
            ],
        }, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "Bundle":
        data = json.loads(raw)
        v = data.get("version")
        if v != BUNDLE_VERSION:
            raise ValueError(f"unsupported bundle version: {v!r}")
        items = {
            d["isadg_id"]: [PageRef(p["root_id"], p["page_key"])
                            for p in d["matched_pages"]]
            for d in data.get("selected_items", [])
        }
        states = {
            PageRef(d["root_id"], d["page_key"]): d["state"]
            for d in data.get("page_state", [])
        }
        return cls(selected_items=items, page_state=states)
