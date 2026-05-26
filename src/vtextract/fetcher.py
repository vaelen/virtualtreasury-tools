from __future__ import annotations

from vtextract.archive import Archive
from vtextract.client import Client
from vtextract.models import Page, PageRef, Record
from vtextract.schema import (
    neighbor_canvases,
    normalize_record,
    parse_manifest,
    reconstruct_text,
    volume_info,
)


def fetch_resource(
    client: Client,
    archive: Archive,
    search_hit: dict,
    *,
    search_id: str,
    context_pages: int = 1,
    _root_manifest_cache: dict | None = None,
) -> Record:
    """Fetch one resource: detail metadata, manifest, images, transcriptions.

    Stores each physical page once in the shared per-volume page store and
    writes the resource record referencing its primary and context pages.
    """
    isadg_id = int(search_hit["isadgID"])
    cache = _root_manifest_cache if _root_manifest_cache is not None else {}

    try:
        detail = client.get_json(f"/rest/isadg-identity-statements/{isadg_id}")
        manifest = client.get_json(f"/iiif/v1/{isadg_id}/manifest")
        primary_pages = parse_manifest(manifest)

        page_refs: list[PageRef] = []
        for page in primary_pages:
            _ensure_page(client, archive, page, role="primary", refs=page_refs)
            for ctx in _context_for(client, cache, archive, page, context_pages):
                _ensure_page(client, archive, ctx, role="context", refs=page_refs)

        record = normalize_record(search_hit, detail)
        record.pages = page_refs
        archive.write_resource(record, manifest=manifest)
        archive.mark_resource_complete(isadg_id, pages=[r.page_key for r in page_refs], search_id=search_id)
        archive.save_state()
        return record
    except Exception as exc:  # noqa: BLE001 - record failure and re-raise for the caller to log
        archive.mark_resource_failed(isadg_id, reason=repr(exc))
        archive.save_state()
        raise


def _context_for(client: Client, cache: dict, archive: Archive, page: Page, context_pages: int) -> list[Page]:
    if context_pages <= 0:
        return []
    if page.root_id not in cache:
        root_manifest = client.get_json(f"/iiif/v1/{page.root_id}/manifest")
        cache[page.root_id] = root_manifest
        archive.write_volume_info(page.root_id, volume_info(root_manifest))
    return neighbor_canvases(cache[page.root_id], page.canvas_id, context_pages)


def _ensure_page(
    client: Client,
    archive: Archive,
    page: Page,
    *,
    role: str,
    refs: list[PageRef],
) -> None:
    if not page.page_key:
        return
    ref = PageRef(
        page_key=page.page_key,
        root_id=page.root_id,
        role=role,
        path=archive.page_relative_path(page.root_id, page.page_key),
        canvas_label=page.canvas_label,
        width=page.width,
        height=page.height,
    )
    # avoid duplicate refs within a single resource
    if any(r.page_key == ref.page_key for r in refs):
        return
    refs.append(ref)

    if archive.has_page(page.root_id, page.page_key):
        return

    image_bytes = client.get_bytes(page.image_url)
    text = None
    annotations = None
    if page.annotation_list_urls:
        annotations = client.get_json(page.annotation_list_urls[0])
        text = reconstruct_text(annotations)
    archive.store_page(
        root_id=page.root_id,
        page_key=page.page_key,
        image_bytes=image_bytes,
        text=text,
        annotations=annotations,
    )
