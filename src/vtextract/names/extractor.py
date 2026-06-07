# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.progress import Progress

from vtextract.names import llm as llm_module
from vtextract.names.chunking import chunk_text
from vtextract.names.merge import merge_people
from vtextract.names.models import (
    ERROR_SIDECAR_SCHEMA,
    SIDECAR_SCHEMA,
    NamesStats,
    Person,
    Usage,
    people_and_usage,
    person_to_entry,
    sum_usage,
)
from vtextract.schema import normalize_reference_code

# (chunk_text, model, api_base) -> people for that chunk.
FindFn = Callable[[str, str, "str | None"], "list[Person]"]

_TXT_SUFFIX = ".txt"
_SIDECAR_SUFFIX = ".names.json"
_ERROR_SUFFIX = ".names.error.json"


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


@dataclass(frozen=True)
class ErrorRecord:
    """One parsed persistent-failure sidecar, for listing."""
    root_id: str
    page_key: str
    error_class: str
    finish_reason: str | None
    attempts: int
    last_attempt: str
    message: str
    model: str


def iter_error_sidecars(
    archive: Path, scope_pages: set[tuple[str, str]] | None = None,
) -> list[ErrorRecord]:
    """Parse every {page_key}.names.error.json under archive/pages.

    ``scope_pages``, when given, limits the result to those (root_id, page_key)
    pairs. Malformed files are skipped (a half-written sidecar shouldn't crash a
    listing).
    """
    out: list[ErrorRecord] = []
    pages_dir = Path(archive) / "pages"
    if not pages_dir.is_dir():
        return out
    for err in sorted(pages_dir.glob("*/*.jpg.names.error.json")):
        root_id = err.parent.name
        page_key = err.name[: -len(_ERROR_SUFFIX)]  # keeps trailing .jpg
        if scope_pages is not None and (root_id, page_key) not in scope_pages:
            continue
        try:
            data = json.loads(err.read_text())
        except (OSError, ValueError):
            continue
        out.append(ErrorRecord(
            root_id=root_id,
            page_key=page_key,
            error_class=str(data.get("error_class", "")),
            finish_reason=data.get("finish_reason"),
            attempts=int(data.get("attempts", 0)),
            last_attempt=str(data.get("last_attempt", "")),
            message=str(data.get("message", "")),
            model=str(data.get("model", "")),
        ))
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


def _write_sidecar_atomic(path: Path, model: str, people: list[Person],
                          usage: Usage | None = None,
                          elapsed_ms: int | None = None) -> None:
    data: dict = {
        "schema": SIDECAR_SCHEMA,
        "model": model,
        "people": [person_to_entry(p) for p in people],
    }
    if elapsed_ms is not None:  # wall-clock for the page; always set in practice
        data["elapsed_ms"] = elapsed_ms
    if usage is not None:  # omit when untracked, so it's never confused with 0
        data["usage"] = usage.to_dict()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def error_sidecar_for(txt_path: Path) -> Path:
    """Map <page_key>.txt -> <page_key>.names.error.json (same directory)."""
    txt_path = Path(txt_path)
    return txt_path.with_name(txt_path.name[: -len(_TXT_SUFFIX)] + _ERROR_SUFFIX)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_error_sidecar(txt_path: Path, *, model: str, error_class: str,
                         finish_reason: str | None, message: str) -> None:
    """Write/refresh the persistent-failure sidecar for a page.

    Read-modify-write of ``attempts`` (prior count + 1). Per-page file, so this
    is safe under --workers. Atomic via temp-then-os.replace, like the success
    sidecar.
    """
    path = error_sidecar_for(txt_path)
    prior = 0
    if path.exists():
        try:
            prior = int(json.loads(path.read_text()).get("attempts", 0))
        except (OSError, ValueError):
            prior = 0
    data = {
        "schema": ERROR_SIDECAR_SCHEMA,
        "model": model,
        "error_class": error_class,
        "finish_reason": finish_reason,
        "attempts": prior + 1,
        "last_attempt": _utc_now_iso(),
        "message": message,
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
) -> tuple[list[Person], Usage | None]:
    """Extract (people, token usage) for one page.

    Raises if *any* chunk fails: a page is all-or-nothing. Writing a sidecar
    from a subset of chunks would silently drop the names in the failed
    chunk(s) and mark the page done, so it would never be reprocessed. Usage is
    summed across every chunk (None if the find seam reports none).
    """
    text = txt_path.read_text()
    groups: list[list[Person]] = []
    usages: list[Usage | None] = []
    chunks = chunk_text(text, chunk_size, overlap)
    for index, (window, _offset) in enumerate(chunks):
        try:
            people, usage = people_and_usage(find(window, model, api_base))
        except Exception as exc:
            raise RuntimeError(
                f"chunk {index + 1}/{len(chunks)} failed for {txt_path}: {exc}"
            ) from exc
        groups.append(people)
        usages.append(usage)
    return merge_people(groups), sum_usage(usages)


def extract(
    archive: Path,
    *,
    model: str,
    api_base: str | None = None,
    chunk_size: int = 64000,
    overlap: int = 512,
    workers: int = 1,
    max_output_tokens: int = 12000,
    find: FindFn | None = None,
    force: bool = False,
    retry_failed: bool = False,
    scope_pages: set[tuple[str, str]] | None = None,
    show_progress: bool = True,
) -> NamesStats:
    """Walk page transcriptions, extract people, write/refresh sidecars.

    Skips pages whose success sidecar already exists unless ``force``. Pages with
    a persistent-error sidecar are skipped (parked) unless ``force`` or
    ``retry_failed``. ``scope_pages``, when given, limits work to those
    (root_id, page_key) pairs. A page whose extraction fails transiently is left
    without a sidecar so a later run retries it; a persistent failure is parked.
    """
    # Bind the output-token guardrail into the real find_people. Injected test
    # seams keep the plain 3-arg FindFn shape and ignore the cap (no LLM call).
    if find is None:
        def find(text: str, model: str, api_base: str | None = None):
            return llm_module.find_people(
                text, model, api_base, max_output_tokens=max_output_tokens)
    archive = Path(archive)
    stats = NamesStats()

    todo: list[tuple[str, Path]] = []  # (page_key, txt_path) — root_id unused downstream
    for root_id, page_key, txt in page_transcriptions(archive):
        if scope_pages is not None and (root_id, page_key) not in scope_pages:
            continue
        side = sidecar_for(txt)
        if side.exists() and not force:
            stats.skipped += 1
            error_sidecar_for(txt).unlink(missing_ok=True)  # success wins
            continue
        if error_sidecar_for(txt).exists() and not force and not retry_failed:
            stats.parked += 1
            continue
        todo.append((page_key, txt))

    def work(txt: Path,
             ) -> tuple[Path, list[Person] | None, Usage | None, int | None, Exception | None]:
        # Wall-clock for the whole page (dominated by the LLM call(s); a page
        # may span several chunks plus a JSON-repair retry). Each page is timed
        # in its own thread, so the figure is correct under --workers > 1.
        start = time.monotonic()
        try:
            people, usage = _extract_one(
                txt, model=model, api_base=api_base,
                chunk_size=chunk_size, overlap=overlap, find=find)
            elapsed_ms = round((time.monotonic() - start) * 1000)
            return txt, people, usage, elapsed_ms, None
        except Exception as exc:
            return txt, None, None, None, exc

    def run(progress: Progress | None, task_id) -> None:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futures = [ex.submit(work, txt) for _key, txt in todo]
            for fut in as_completed(futures):
                txt, people, usage, elapsed_ms, exc = fut.result()
                if people is None:
                    cls = llm_module.error_class(exc) if exc else None
                    if cls is not None:
                        _write_error_sidecar(
                            txt, model=model, error_class=cls,
                            finish_reason=llm_module.truncation_finish_reason(exc),
                            message=llm_module.friendly_error(exc, model, api_base))
                        stats.failed_persistent += 1
                    else:
                        stats.failed += 1
                    _log_failure(progress, txt, exc, model, api_base)
                else:
                    _write_sidecar_atomic(sidecar_for(txt), model, people, usage,
                                          elapsed_ms)
                    error_sidecar_for(txt).unlink(missing_ok=True)
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
