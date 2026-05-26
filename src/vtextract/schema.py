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
    after = image_url.split("/loris/", 1)[1]
    return unquote(after.split("/", 1)[0])


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
