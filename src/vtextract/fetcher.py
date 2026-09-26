# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from vtextract.archive import Archive
from vtextract.client import Client
from vtextract.models import Page, PageRef, Record
from vtextract.schema import (
    detail_title,
    neighbor_canvases,
    normalize_record,
    normalize_reference_code,
    parse_manifest,
    reconstruct_text,
    volume_info,
)

IDENTITY_STATEMENT_PATH = "/rest/isadg-identity-statements/"


def _fetch_detail(client: Client, search_hit: dict) -> dict:
    """Fetch the identity-statement detail a hit points at.

    A numeric `isadgID` is looked up by id; otherwise the hit's
    `displayReferenceCode` is normalised and resolved by reference code. Either
    way the response is the same detail object, and it is the only thing the
    archive output is built from.
    """
    raw_id = search_hit.get("isadgID")
    if raw_id is not None and str(raw_id).isdigit():
        return client.get_json(f"{IDENTITY_STATEMENT_PATH}{int(raw_id)}")
    code = search_hit.get("displayReferenceCode")
    if code:
        norm = normalize_reference_code(code)
        return client.get_json(f"{IDENTITY_STATEMENT_PATH}?isadgReferenceCode={quote(norm)}")
    raise ValueError(f"hit has neither a numeric isadgID nor a displayReferenceCode: {search_hit!r}")


def fetch_resource(
    client: Client,
    archive: Archive,
    search_hit: dict,
    *,
    search_id: str,
    context_pages: int = 1,
    images: bool = False,
    on_item_start: Callable[[int], None] | None = None,
    on_page: Callable[[], None] | None = None,
    refresh: bool = False,
    on_verify: Callable[[str, str], None] | None = None,
    image_pages: set[str] | None = None,
    _root_manifest_cache: dict | None = None,
    _verified_pages: set[str] | None = None,
) -> Record:
    """Fetch one resource: detail metadata, manifest, transcriptions, (optionally) images.

    With ``images=False`` (the default), only the detail object, the manifest,
    and per-page annotation lists are fetched; image bytes are skipped. The
    resource state records the mode so a later ``images=True`` run can backfill
    the images.

    ``image_pages`` (when not ``None``) is an allowlist of ``page_key``s: image
    bytes are downloaded/verified only for pages in the set, so a page-level
    bundle can backfill just its selected pages instead of the whole resource
    (which may be an entire volume). Metadata and transcriptions are unaffected.

    Stores each physical page once in the shared per-volume page store and
    writes the resource record referencing its primary and context pages.

    For progress reporting, ``on_item_start`` is called once with the total
    number of pages to process (primary + context), then ``on_page`` is called
    after each page.

    When ``refresh=True`` and ``images=True``, existing images are HEAD-verified
    against the server; mismatched or missing images are re-downloaded.
    ``on_verify`` receives ``(outcome, relative_path)`` for each page verified.
    Pass a shared ``_verified_pages`` set across calls to avoid re-HEADing the
    same page. ``refresh=True`` with ``images=False`` re-fetches metadata and
    backfills any missing transcriptions, leaving images on disk untouched.
    """
    cache = _root_manifest_cache if _root_manifest_cache is not None else {}
    verified = _verified_pages if _verified_pages is not None else set()
    # The hit only tells us which detail object to fetch; everything else is
    # derived from that detail, whose `id` is the canonical isadgID.
    detail = _fetch_detail(client, search_hit)
    isadg_id = int(detail["id"])

    try:
        manifest = client.get_json(f"/iiif/v1/{isadg_id}/manifest")
        # Plan the full set of pages first (this fetches the cached root
        # manifest for context) so the page count is known before downloading.
        work: list[tuple[Page, str]] = []
        for page in parse_manifest(manifest):
            work.append((page, "primary"))
            for ctx in _context_for(client, cache, archive, page, context_pages):
                work.append((ctx, "context"))
        if on_item_start is not None:
            on_item_start(len(work))

        page_refs: list[PageRef] = []
        for page, role in work:
            _ensure_page(
                client, archive, page, role=role, refs=page_refs,
                images=images, refresh=refresh, verified=verified, on_verify=on_verify,
                image_pages=image_pages,
            )
            if on_page is not None:
                on_page()

        record = normalize_record(detail)
        record.pages = page_refs
        archive.write_resource(record, manifest=manifest)
        archive.mark_resource_complete(
            isadg_id, pages=[r.page_key for r in page_refs], search_id=search_id,
            images_downloaded=images,
        )
        archive.save_state()
        return record
    except Exception as exc:  # noqa: BLE001 - record failure and re-raise for the caller to log
        archive.mark_resource_failed(isadg_id, reason=repr(exc))
        archive.save_state()
        raise


def _volume_title(client: Client, root_id: str) -> str | None:
    """Best-effort descriptive title for the volume root; None if unavailable."""
    try:
        detail = client.get_json(f"{IDENTITY_STATEMENT_PATH}{root_id}")
    except Exception:  # noqa: BLE001 - title is optional; never block the volume record
        return None
    return detail_title(detail) or None


def _context_for(client: Client, cache: dict, archive: Archive, page: Page, context_pages: int) -> list[Page]:
    if context_pages <= 0:
        return []
    if page.root_id not in cache:
        root_manifest = client.get_json(f"/iiif/v1/{page.root_id}/manifest")
        cache[page.root_id] = root_manifest
        title = _volume_title(client, page.root_id)
        archive.write_volume_info(page.root_id, volume_info(root_manifest, title=title))
    return neighbor_canvases(cache[page.root_id], page.canvas_id, context_pages)


def _download_page(client: Client, archive: Archive, page: Page, *, want_image: bool) -> None:
    """Download a page's transcription (if any) and, when requested, its image.

    Annotations are always fetched when the manifest advertised an annotation
    list; image bytes are fetched only when ``want_image`` is True.
    """
    image_bytes = client.get_bytes(page.image_url) if want_image else None
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


def _verify_or_redownload(client: Client, archive: Archive, page: Page) -> str:
    """HEAD-verify a page image against the on-disk size; re-download on mismatch.

    Returns the outcome: "ok" (size matched), "mismatch" (re-downloaded),
    "missing" (file absent, downloaded), or "unverified" (HEAD failed or had no
    Content-Length; file left untouched).
    """
    disk_size = archive.page_size(page.root_id, page.page_key)
    if disk_size is None:
        _download_page(client, archive, page, want_image=True)
        return "missing"
    try:
        head_size = client.head(page.image_url)
    except Exception:  # noqa: BLE001 - cannot verify; leave the file as-is
        return "unverified"
    if head_size is None:
        return "unverified"
    if head_size == disk_size:
        return "ok"
    _download_page(client, archive, page, want_image=True)
    return "mismatch"


def _ensure_page(
    client: Client,
    archive: Archive,
    page: Page,
    *,
    role: str,
    refs: list[PageRef],
    images: bool = False,
    refresh: bool = False,
    verified: set[str] | None = None,
    on_verify: Callable[[str, str], None] | None = None,
    image_pages: set[str] | None = None,
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

    has_image = archive.has_page_image(page.root_id, page.page_key)
    has_text = archive.has_page_transcription(page.root_id, page.page_key)
    expects_text = bool(page.annotation_list_urls)
    # When an allowlist is given, only its pages are eligible for image bytes.
    image_allowed = image_pages is None or page.page_key in image_pages

    if not refresh:
        need_image = images and image_allowed and not has_image
        need_text = expects_text and not has_text
        if need_image or need_text:
            _download_page(client, archive, page, want_image=need_image)
        return

    # refresh mode: always backfill any missing transcription; only HEAD-verify
    # the image when the caller wants images.
    if expects_text and not has_text:
        _download_page(client, archive, page, want_image=False)

    if not images or not image_allowed:
        return

    key = f"{page.root_id}/{page.page_key}"
    if verified is not None and key in verified:
        return
    outcome = _verify_or_redownload(client, archive, page)
    if verified is not None:
        verified.add(key)
    if on_verify is not None:
        on_verify(outcome, archive.page_relative_path(page.root_id, page.page_key))
