# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
from pathlib import Path

from vtextract.index.models import ItemRow, PageLink, VolumeRow

# Description is composed from these searchHit fields, in this order. Each is a
# list of strings on the search hit (may be empty or absent).
_DESCRIPTION_FIELDS = (
    "scopeAndContent",
    "archivalHistory",
    "archivistsNote",
    "administrativeOrBiographicalHistory",
    "note",
)


def compose_description(search_hit: dict) -> str:
    """Join the free-text description fields into one newline-separated blob."""
    parts: list[str] = []
    for field in _DESCRIPTION_FIELDS:
        for value in search_hit.get(field) or []:
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def date_bounds(search_hit: dict, kind: str) -> tuple[str | None, str | None]:
    """Return (begin, end) ISO dates for kind in {"content", "created"}."""
    key = "contentDate" if kind == "content" else "createdDate"
    span = search_hit.get(key) or {}
    return span.get("gte"), span.get("lte")


def read_item(meta_path: Path) -> ItemRow:
    """Parse an items/<id>/metadata.json into an ItemRow."""
    data = json.loads(Path(meta_path).read_text())
    hit = data.get("searchHit") or {}
    pages = [
        PageLink(root_id=str(p["root_id"]), page_key=p["page_key"], role=p.get("role", "primary"))
        for p in data.get("pages") or []
    ]
    content_begin, content_end = date_bounds(hit, "content")
    created_begin, created_end = date_bounds(hit, "created")
    volumes: list[str] = []
    for p in pages:
        if p.root_id not in volumes:
            volumes.append(p.root_id)
    return ItemRow(
        isadg_id=int(data["isadgID"]),
        reference_code=data.get("referenceCode") or "",
        title=data.get("title") or hit.get("displayTitle") or "",
        description=compose_description(hit),
        repository=hit.get("documentRepositoryName"),
        content_begin=content_begin,
        content_end=content_end,
        created_begin=created_begin,
        created_end=created_end,
        volumes=volumes,
        pages=pages,
    )


def read_volume(volume_path: Path, *, root_id: str) -> VolumeRow:
    data = json.loads(Path(volume_path).read_text())
    return VolumeRow(
        root_id=root_id,
        label=data.get("label"),
        reference_code=data.get("reference_code"),
    )


def read_transcription(txt_path: Path) -> str:
    return Path(txt_path).read_text()
