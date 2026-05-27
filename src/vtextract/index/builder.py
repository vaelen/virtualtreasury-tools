# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from pathlib import Path

from vtextract.index.db import IndexDB
from vtextract.index.models import BuildStats
from vtextract.index.reader import read_item, read_transcription, read_volume

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
    return out


def build(archive, *, rebuild: bool = False, reporter=None) -> BuildStats:
    """(Re)build the index from the archive. Incremental unless rebuild=True."""
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
                _index_one(db, kind, relpath, abspath, st)
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
        # prune vanished sources
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


def _index_one(db: IndexDB, kind: str, relpath: str, abspath: Path, st) -> None:
    fp = (relpath, st.st_mtime, st.st_size)
    if kind == "item":
        db.upsert_item(read_item(abspath), fingerprint=fp)
    elif kind == "volume":
        root_id = abspath.parent.name
        db.upsert_volume(read_volume(abspath, root_id=root_id), fingerprint=fp)
    elif kind == "transcription":
        root_id = abspath.parent.name
        page_key = abspath.name[: -len(".txt")]  # strip .txt; page_key keeps .jpg
        db.upsert_transcription(root_id, page_key, read_transcription(abspath), fingerprint=fp)
