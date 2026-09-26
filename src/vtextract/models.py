# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field

# CLI field-flag name -> the value the backend expects in kwSearchFieldList.
FIELD_MAP = {
    "keyword": "all",
    "title": "title",
    "transcription": "kwTranscription",
    "creator": "creator",
    "person": "kg_label",
    "place": "kg_label",
    "ref": "referenceCode",
}
# CLI operand-flag name -> the value the backend expects in kwOperList.
OPERANDS = {"all": "ALL", "any": "ANY", "none": "NONE", "exact": "EXACT"}
# Field flags that also set boostItemsWithKGEntityType.
BOOST_FOR_FIELD = {"person": "Person", "place": "Place"}


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
    """A catalogued resource (isadgID). All fields derive from the detail object."""

    isadg_id: int
    reference_code: str
    title: str
    detail: dict | None = None
    pages: list[PageRef] = field(default_factory=list)


@dataclass
class Filter:
    """One search clause: a field, an operand, and the keywords to match."""

    field: str                          # kwSearchFieldList value, e.g. "all", "kg_label"
    operand: str                        # "ALL" | "ANY" | "NONE" | "EXACT"
    keywords: list[str]                 # joined by spaces into one kwList entry


@dataclass
class SearchCriteria:
    """A complete explicit search: parallel filters plus scalar options."""

    filters: list[Filter] = field(default_factory=list)
    start: str | None = None            # -> searchContentDate_begin (yyyy-mm-dd)
    end: str | None = None              # -> searchContentDate_end
    boost: str | None = None            # -> boostItemsWithKGEntityType ("Person"/"Place")
    sorting: str = "relevance"          # -> resultSorting ("relevance"/"ascending"/"descending")
