# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import re
from urllib.parse import unquote

from vtextract.models import Page, Record

_ROOT_ID_RE = re.compile(r"/iiif/v1/(\d+)/")


def extract_root_id(iiif_url: str) -> str:
    """Extract the volume manifest-root id embedded in a IIIF canvas/list @id."""
    match = _ROOT_ID_RE.search(iiif_url)
    if not match:
        raise ValueError(f"No IIIF root id found in URL: {iiif_url}")
    return match.group(1)


def loris_filename(image_url: str) -> str:
    """Pull the Loris page identifier out of a full image URL."""
    parts = image_url.split("/loris/", 1)
    if len(parts) != 2:
        raise ValueError(f"Image URL is not a Loris URL (no '/loris/'): {image_url}")
    return unquote(parts[1].split("/", 1)[0])


def parse_manifest(manifest: dict) -> list[Page]:
    """Turn a IIIF Presentation manifest into ordered Page objects (one per canvas)."""
    pages: list[Page] = []
    for sequence in manifest.get("sequences", []):
        for canvas in sequence.get("canvases", []):
            pages.append(_parse_canvas(canvas))
    return pages


def _parse_canvas(canvas: dict) -> Page:
    canvas_id = canvas["@id"]
    images = canvas.get("images", [])
    resource = images[0]["resource"] if images else {}
    image_url = resource.get("@id", "")
    annotation_list_urls = [
        oc["@id"] for oc in canvas.get("otherContent", []) if "@id" in oc
    ]
    return Page(
        page_key=loris_filename(image_url) if image_url else "",
        image_url=image_url,
        annotation_list_urls=annotation_list_urls,
        root_id=extract_root_id(canvas_id),
        canvas_id=canvas_id,
        canvas_label=canvas.get("label"),
        width=canvas.get("width") or resource.get("width"),
        height=canvas.get("height") or resource.get("height"),
    )


def reconstruct_text(annotation_list: dict) -> str:
    """Concatenate a page's text annotation fragments in document order."""
    chars: list[str] = []
    for annotation in annotation_list.get("resources", []):
        resource = annotation.get("resource", {})
        text = resource.get("chars")
        if text is not None:
            chars.append(text)
    return "\n".join(chars)


def neighbor_canvases(root_manifest: dict, canvas_id: str, n: int) -> list[Page]:
    """Return the n canvases before and after `canvas_id` in the volume sequence.

    The target canvas itself is excluded. Out-of-range neighbours are clipped.
    Returns [] if the canvas is not found or n <= 0.
    """
    if n <= 0:
        return []
    pages = parse_manifest(root_manifest)
    index = next((i for i, p in enumerate(pages) if p.canvas_id == canvas_id), None)
    if index is None:
        return []
    start = max(0, index - n)
    end = min(len(pages), index + n + 1)
    return [p for i, p in enumerate(pages[start:end], start=start) if i != index]


def normalize_reference_code(code: str) -> str:
    """Canonicalise a reference code for the isadgReferenceCode query.

    Reference codes are written with spaces or slashes (`TNA SO 1/14`); the API
    expects each separator as a dash (`TNA-SO-1-14`).
    """
    return code.replace(" ", "-").replace("/", "-")


def normalize_record(search_hit: dict, detail: dict | None) -> Record:
    """Build a Record from a search hit and (optional) detail record.

    Search hits carry `displayReferenceCode`/`displayTitle`; a bare hit from
    `get <numeric id>` does not, so fall back to the detail record's preferred
    reference code and title.
    """
    detail = detail or {}
    reference_code = (
        search_hit.get("displayReferenceCode")
        or detail.get("preferredReferenceCode", {}).get("referenceCode")
        or ""
    )
    title = (
        search_hit.get("displayTitle")
        or detail.get("preferredTitle", {}).get("title")
        or ""
    )
    return Record(
        isadg_id=int(search_hit["isadgID"]),
        reference_code=reference_code,
        title=title,
        search_hit=search_hit,
        detail=detail or None,
    )


def volume_info(manifest: dict) -> dict:
    """Extract a human-readable label and reference code from a IIIF manifest."""
    info = {"label": manifest.get("label"), "reference_code": None}
    for entry in manifest.get("metadata", []):
        if entry.get("label") == "ReferenceCode":
            info["reference_code"] = entry.get("value")
    return info
