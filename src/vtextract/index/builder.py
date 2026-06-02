# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
from pathlib import Path

from vtextract.index.dates import parse_year_range
from vtextract.index.db import IndexDB
from vtextract.index.models import BuildStats, ItemRow
from vtextract.index.reader import read_item, read_names, read_transcription, read_volume

INDEX_RELPATH = Path("index") / "vtindex.sqlite3"


def _candidates(archive: Path) -> list[tuple[str, str, Path]]:
    """Return (kind, relpath, abspath) for every source file in the archive."""
    out: list[tuple[str, str, Path]] = []
    items_dir = archive / "items"
    if items_dir.is_dir():
        for meta in sorted(items_dir.glob("*/metadata.json")):
            out.append(("item", f"items/{meta.parent.name}/metadata.json", meta))
    pages_dir = archive / "pages"
    if pages_dir.is_dir():
        for vol in sorted(pages_dir.glob("*/volume.json")):
            out.append(("volume", f"pages/{vol.parent.name}/volume.json", vol))
        for txt in sorted(pages_dir.glob("*/*.jpg.txt")):
            out.append(("transcription", f"pages/{txt.parent.name}/{txt.name}", txt))
        for side in sorted(pages_dir.glob("*/*.jpg.names.json")):
            out.append(("names", f"pages/{side.parent.name}/{side.name}", side))
    return out


def build(archive, *, rebuild: bool = False, reporter=None, cancel=None) -> BuildStats:
    """(Re)build the index from the archive. Incremental unless rebuild=True.

    ``cancel`` is an optional object with ``is_set() -> bool`` (e.g.
    threading.Event); when it becomes set the file loop stops early and the
    prune step is skipped so a cancelled build never deletes unseen sources.
    """
    archive = Path(archive)
    db = IndexDB(archive / INDEX_RELPATH, rebuild=rebuild)
    stats = BuildStats()
    try:
        candidates = _candidates(archive)
        fingerprints = db.fingerprints()
        seen: set[str] = set()
        if reporter is not None:
            reporter.start(len(candidates))
        for kind, relpath, abspath in candidates:
            if cancel is not None and cancel.is_set():
                break
            seen.add(relpath)
            st = abspath.stat()
            fp = (st.st_mtime, st.st_size)
            prior = fingerprints.get(relpath)
            if prior == fp:
                stats.unchanged += 1
                if reporter is not None:
                    reporter.advance()
                continue
            try:
                _index_one(db, kind, relpath, abspath, st, archive=archive)
            except Exception:
                stats.skipped += 1
                if reporter is not None:
                    reporter.advance()
                continue
            if prior is None:
                stats.added += 1
            else:
                stats.updated += 1
            if reporter is not None:
                reporter.advance()
        # prune vanished sources — skip entirely if cancelled, since `seen` is
        # only partial and would otherwise delete sources we never looked at.
        if cancel is None or not cancel.is_set():
            for relpath in set(fingerprints) - seen:
                db.delete_source(relpath)
                stats.removed += 1
        db.set_meta("item_count", str(db.counts()["items"]))
        db.commit()
    finally:
        if reporter is not None:
            reporter.finish(
                added=stats.added, updated=stats.updated, removed=stats.removed,
                unchanged=stats.unchanged, skipped=stats.skipped,
            )
        db.close()
    return stats


def is_stale(db: IndexDB, archive: Path) -> bool:
    """True if any source file is new/changed/removed vs stored fingerprints."""
    fingerprints = db.fingerprints()
    seen: set[str] = set()
    for _kind, relpath, abspath in _candidates(archive):
        seen.add(relpath)
        st = abspath.stat()
        if fingerprints.get(relpath) != (st.st_mtime, st.st_size):
            return True
    return bool(set(fingerprints) - seen)


def _index_one(
    db: IndexDB, kind: str, relpath: str, abspath: Path, st, *, archive: Path
) -> None:
    fp = (relpath, st.st_mtime, st.st_size)
    if kind == "item":
        item = read_item(abspath)
        _populate_estimated_date(item, archive)
        db.upsert_item(item, fingerprint=fp)
    elif kind == "volume":
        root_id = abspath.parent.name
        db.upsert_volume(read_volume(abspath, root_id=root_id), fingerprint=fp)
    elif kind == "transcription":
        root_id = abspath.parent.name
        page_key = abspath.name[: -len(".txt")]  # strip .txt; page_key keeps .jpg
        db.upsert_transcription(root_id, page_key, read_transcription(abspath), fingerprint=fp)
    elif kind == "names":
        root_id = abspath.parent.name
        page_key = abspath.name[: -len(".names.json")]  # page_key keeps .jpg
        db.upsert_names(root_id, page_key, read_names(abspath), fingerprint=fp)


def _populate_estimated_date(item: ItemRow, archive: Path) -> None:
    """Set item.estimated_* from each related volume's title in pages order,
    falling back to the item's own title. Reference codes (item + volumes) are
    stripped from candidate text so catalogue path digits don't masquerade as
    years.
    """
    ignore_codes: list[str] = []
    if item.reference_code:
        ignore_codes.append(item.reference_code)
    volume_titles: list[str] = []
    for root_id in item.volumes:
        vol_path = archive / "pages" / root_id / "volume.json"
        if not vol_path.exists():
            continue
        try:
            data = json.loads(vol_path.read_text())
        except (OSError, ValueError):
            continue
        title = data.get("title") or ""
        ref = data.get("reference_code") or ""
        if title:
            volume_titles.append(title)
        if ref:
            ignore_codes.append(ref)
    for title in volume_titles:
        begin, end = parse_year_range(title, ignore=ignore_codes)
        if begin is not None:
            item.estimated_begin = begin
            item.estimated_end = end
            item.estimated_source = "volume"
            return
    begin, end = parse_year_range(item.title or "", ignore=ignore_codes)
    if begin is not None:
        item.estimated_begin = begin
        item.estimated_end = end
        item.estimated_source = "item_title"
