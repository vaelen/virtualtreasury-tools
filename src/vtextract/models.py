# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    """A physical page parsed from a IIIF canvas."""

    page_key: str                       # Loris identifier, e.g. "IMC_1954_RoD_1_Page_253.jpg"
    image_url: str                      # full-resolution image URL from the manifest
    annotation_list_urls: list[str]     # transcription annotation lists for this page
    root_id: str                        # volume id, from the canvas @id
    canvas_id: str
    canvas_label: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class PageRef:
    """A resource's reference to a stored page."""

    page_key: str
    root_id: str
    role: str                           # "primary" | "context"
    path: str                           # relative path "pages/{root_id}/{page_key}"
    canvas_label: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class Record:
    """A catalogued resource (isadgID)."""

    isadg_id: int
    reference_code: str
    title: str
    search_hit: dict
    detail: dict | None = None
    pages: list[PageRef] = field(default_factory=list)
