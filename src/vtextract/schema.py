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
