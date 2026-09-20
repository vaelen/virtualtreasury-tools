# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
from pathlib import Path

from vtextract.index.models import ItemRow, PageFiles, PageLink, PersonRow, VolumePage, VolumeRow

# Description is composed from these free-text fields, in this order. Each entry
# is (detail array key, field on each array element); the identity-statement
# detail groups them into separate sub-resource lists, any of which may be
# empty or absent.
_DESCRIPTION_FIELDS = (
    ("isadgContentAndStructure", "scopeAndContent"),
    ("isadgContexts", "archivalHistory"),
    ("isadgDescriptionControls", "archivistsNote"),
    ("isadgContexts", "administrativeOrBiographicalHistory"),
    ("isadgNotes", "note"),
)

# eventType.name on an isadgDates entry, per date kind.
_DATE_EVENT_NAME = {"content": "Content Date", "created": "Created"}


def compose_description(detail: dict) -> str:
    """Join the free-text description fields from a detail object into one blob."""
    parts: list[str] = []
    for array_key, field in _DESCRIPTION_FIELDS:
        for entry in detail.get(array_key) or []:
            value = entry.get(field)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def date_bounds(detail: dict, kind: str) -> tuple[str | None, str | None]:
    """Return (begin, end) ISO dates for kind in {"content", "created"}.

    Dates live in detail["isadgDates"], one entry per event keyed by
    eventType.name. The outer span of the timespan (beginOfBegin .. endOfEnd)
    is the inclusive range, so a single-day POINT collapses to (d, d) and a
    PERIOD spans the whole interval.
    """
    target = _DATE_EVENT_NAME[kind]
    for entry in detail.get("isadgDates") or []:
        if (entry.get("eventType") or {}).get("name") == target:
            span = entry.get("timespan") or {}
            return span.get("beginOfBegin"), span.get("endOfEnd")
    return None, None


def read_item(meta_path: Path) -> ItemRow:
    """Parse an items/<id>/metadata.json into an ItemRow."""
    data = json.loads(Path(meta_path).read_text())
    detail = data.get("detail") or {}
    pages = [
        PageLink(root_id=str(p["root_id"]), page_key=p["page_key"], role=p.get("role", "primary"))
        for p in data.get("pages") or []
    ]
    content_begin, content_end = date_bounds(detail, "content")
    created_begin, created_end = date_bounds(detail, "created")
    volumes: list[str] = []
    for p in pages:
        if p.root_id not in volumes:
            volumes.append(p.root_id)
    return ItemRow(
        isadg_id=int(data["isadgID"]),
        reference_code=data.get("referenceCode") or "",
        title=data.get("title") or (detail.get("preferredTitle") or {}).get("title") or "",
        description=compose_description(detail),
        repository=(detail.get("documentRepository") or {}).get("name"),
        content_begin=content_begin,
        content_end=content_end,
        created_begin=created_begin,
        created_end=created_end,
        volumes=volumes,
        pages=pages,
    )


def read_volume(volume_path: Path, *, root_id: str) -> VolumeRow:
    data = json.loads(Path(volume_path).read_text())
    pages = [
        VolumePage(page_key=p["page_key"], ordinal=i, label=p.get("label"))
        for i, p in enumerate(data.get("pages") or [], start=1)
    ]
    return VolumeRow(
        root_id=root_id,
        label=data.get("label"),
        reference_code=data.get("reference_code"),
        title=data.get("title"),
        pages=pages,
    )


def read_transcription(txt_path: Path) -> str:
    return Path(txt_path).read_text()


def read_names(sidecar_path: Path) -> list[PersonRow]:
    """Parse a pages/<root_id>/<page_key>.names.json sidecar into PersonRows.

    Each person is the compact ``[canonical, *surface_forms]`` array (schema 2).
    """
    data = json.loads(Path(sidecar_path).read_text())
    rows: list[PersonRow] = []
    for entry in data.get("people") or []:
        if not entry:
            continue
        rows.append(PersonRow(canonical=entry[0], aliases=list(entry[1:])))
    return rows


def _resolve(page_dir: Path, name: str) -> str | None:
    path = page_dir / name
    return str(path.resolve()) if path.exists() else None


def page_files(archive: Path, root_id: str, page_key: str) -> PageFiles:
    """Resolve a page's on-disk image/metadata/transcription absolute paths.

    Page store layout (see archive.py): the image is ``{page_key}``, the
    transcription ``{page_key}.txt``, the annotations/metadata ``{page_key}.json``.
    Each field is None when the file is not present.
    """
    page_dir = Path(archive) / "pages" / root_id
    return PageFiles(
        image=_resolve(page_dir, page_key),
        metadata=_resolve(page_dir, f"{page_key}.json"),
        transcription=_resolve(page_dir, f"{page_key}.txt"),
        names=_resolve(page_dir, f"{page_key}.names.json"),
        notes=_resolve(page_dir, f"{page_key}.notes.md"),
    )
