# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.progress import Progress

from vtextract.names import llm as llm_module
from vtextract.names.chunking import chunk_text
from vtextract.names.merge import merge_people
from vtextract.names.models import SIDECAR_SCHEMA, NamesStats, Person
from vtextract.schema import normalize_reference_code

# (chunk_text, model, api_base) -> people for that chunk.
FindFn = Callable[[str, str, "str | None"], "list[Person]"]

_TXT_SUFFIX = ".txt"
_SIDECAR_SUFFIX = ".names.json"


def page_transcriptions(archive: Path) -> list[tuple[str, str, Path]]:
    """Return (root_id, page_key, txt_path) for every page transcription.

    page_key keeps its trailing .jpg (the file is <page_key>.txt).
    """
    out: list[tuple[str, str, Path]] = []
    pages_dir = Path(archive) / "pages"
    if not pages_dir.is_dir():
        return out
    for txt in sorted(pages_dir.glob("*/*.jpg.txt")):
        root_id = txt.parent.name
        page_key = txt.name[: -len(_TXT_SUFFIX)]
        out.append((root_id, page_key, txt))
    return out


def pages_for_resources(archive: Path, identifiers: list[str]) -> set[tuple[str, str]]:
    """Resolve item identifiers (isadgIDs or reference codes) to their pages.

    Returns the set of (root_id, page_key) referenced by the matching items'
    metadata.json. Unknown identifiers contribute nothing.
    """
    want_ids = {tok for tok in identifiers if tok.isdigit()}
    want_codes = {normalize_reference_code(tok) for tok in identifiers if not tok.isdigit()}
    pages: set[tuple[str, str]] = set()
    items_dir = Path(archive) / "items"
    if not items_dir.is_dir():
        return pages
    for meta in items_dir.glob("*/metadata.json"):
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        rid = str(data.get("isadgID"))
        rc = normalize_reference_code(data.get("referenceCode") or "")
        if rid in want_ids or meta.parent.name in want_ids or (rc and rc in want_codes):
            for p in data.get("pages") or []:
                pages.add((str(p["root_id"]), p["page_key"]))
    return pages


def sidecar_for(txt_path: Path) -> Path:
    """Map <page_key>.txt -> <page_key>.names.json (same directory)."""
    txt_path = Path(txt_path)
    return txt_path.with_name(txt_path.name[: -len(_TXT_SUFFIX)] + _SIDECAR_SUFFIX)


def _write_sidecar_atomic(path: Path, model: str, people: list[Person]) -> None:
    data = {
        "schema": SIDECAR_SCHEMA,
        "model": model,
        "people": [p.model_dump() for p in people],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _log_failure(
    progress: Progress | None, txt_path: Path, exc: Exception | None,
    model: str, api_base: str | None,
) -> None:
    """Report a per-page extraction failure to stderr.

    Uses llm.friendly_error to classify the cause (connection, auth, bad
    JSON, ...) so transient failures left for a later retry are diagnosable.
    """
    page = f"{txt_path.parent.name}/{txt_path.name[: -len(_TXT_SUFFIX)]}"
    reason = llm_module.friendly_error(exc, model, api_base) if exc else "unknown error"
    message = f"names: failed {page}: {reason}"
    if progress is not None:
        # print above the live progress bar instead of corrupting it
        progress.console.print(message)
    else:
        print(message, file=sys.stderr)


def _extract_one(
    txt_path: Path, *, model: str, api_base: str | None,
    chunk_size: int, overlap: int, find: FindFn,
) -> list[Person]:
    """Extract people for one page.

    Raises if *any* chunk fails: a page is all-or-nothing. Writing a sidecar
    from a subset of chunks would silently drop the names in the failed
    chunk(s) and mark the page done, so it would never be reprocessed.
    """
    text = txt_path.read_text()
    groups: list[list[Person]] = []
    chunks = chunk_text(text, chunk_size, overlap)
    for index, (window, _offset) in enumerate(chunks):
        try:
            groups.append(find(window, model, api_base))
        except Exception as exc:
            raise RuntimeError(
                f"chunk {index + 1}/{len(chunks)} failed for {txt_path}: {exc}"
            ) from exc
    return merge_people(groups)


def extract(
    archive: Path,
    *,
    model: str,
    api_base: str | None = None,
    chunk_size: int = 64000,
    overlap: int = 512,
    workers: int = 1,
    find: FindFn | None = None,
    force: bool = False,
    scope_pages: set[tuple[str, str]] | None = None,
    show_progress: bool = True,
) -> NamesStats:
    """Walk page transcriptions, extract people, write/refresh sidecars.

    Skips pages whose sidecar already exists unless ``force``. ``scope_pages``,
    when given, limits work to those (root_id, page_key) pairs. A page whose
    extraction fails is left without a sidecar so a later run retries it.
    """
    find = find or llm_module.find_people
    archive = Path(archive)
    stats = NamesStats()

    todo: list[tuple[str, Path]] = []  # (page_key, txt_path) — root_id unused downstream
    for root_id, page_key, txt in page_transcriptions(archive):
        if scope_pages is not None and (root_id, page_key) not in scope_pages:
            continue
        side = sidecar_for(txt)
        if side.exists() and not force:
            stats.skipped += 1
            continue
        todo.append((page_key, txt))

    def work(txt: Path) -> tuple[Path, list[Person] | None, Exception | None]:
        try:
            people = _extract_one(
                txt, model=model, api_base=api_base,
                chunk_size=chunk_size, overlap=overlap, find=find)
            return txt, people, None
        except Exception as exc:
            return txt, None, exc

    def run(progress: Progress | None, task_id) -> None:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futures = [ex.submit(work, txt) for _key, txt in todo]
            for fut in as_completed(futures):
                txt, people, exc = fut.result()
                if people is None:
                    stats.failed += 1
                    _log_failure(progress, txt, exc, model, api_base)
                else:
                    _write_sidecar_atomic(sidecar_for(txt), model, people)
                    stats.extracted += 1
                    stats.people += len(people)
                if progress is not None:
                    progress.advance(task_id)

    if show_progress and todo:
        with Progress(console=Console(stderr=True)) as progress:
            task_id = progress.add_task("Extracting names", total=len(todo))
            run(progress, task_id)
    else:
        run(None, None)
    return stats
