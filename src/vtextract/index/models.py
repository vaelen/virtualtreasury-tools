# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageLink:
    """An item's reference to a physical page."""

    root_id: str
    page_key: str
    role: str  # "primary" | "context"


@dataclass
class ItemRow:
    """A catalogued resource, flattened for indexing."""

    isadg_id: int
    reference_code: str
    title: str
    description: str
    repository: str | None
    content_begin: str | None = None
    content_end: str | None = None
    created_begin: str | None = None
    created_end: str | None = None
    volumes: list[str] = field(default_factory=list)
    pages: list[PageLink] = field(default_factory=list)

    @property
    def path(self) -> str:
        return f"items/{self.isadg_id}"


@dataclass
class VolumePage:
    """One physical page of a volume, in sequence order."""

    page_key: str
    ordinal: int
    label: str | None = None


@dataclass
class VolumeRow:
    root_id: str
    label: str | None
    reference_code: str | None
    title: str | None = None
    pages: list[VolumePage] = field(default_factory=list)


@dataclass
class SearchQuery:
    text: str | None = None
    fields: tuple[str, ...] = ("title", "description", "transcription")
    date_from: str | None = None  # ISO YYYY-MM-DD (inclusive lower bound)
    date_to: str | None = None    # ISO YYYY-MM-DD (inclusive upper bound)
    date_type: str = "content"    # "content" | "created"
    volume: str | None = None
    limit: int = 50


@dataclass
class SearchResult:
    isadg_id: int
    title: str
    reference_code: str
    repository: str | None
    content_date: str | None
    created_date: str | None
    matched_fields: list[str]
    matched_pages: list[tuple[str, str]]  # (root_id, page_key)
    score: float
    path: str


@dataclass
class VolumeInfo:
    root_id: str
    label: str | None
    reference_code: str | None
    item_count: int
    title: str | None = None


@dataclass
class BuildStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: int = 0

    @property
    def processed(self) -> int:
        """Source files looked at this build (excludes vanished/removed)."""
        return self.added + self.updated + self.unchanged + self.skipped
