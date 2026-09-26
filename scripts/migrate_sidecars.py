#!/usr/bin/env python3
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT
"""One-time migration: convert v1 names sidecars to the compact v2 format.

v1 stored each person as a verbose object:
    {"canonical": "B. McHugh", "confidence": "high",
     "aliases": [{"text": "B. Mchugh", "confidence": "high"}]}
v2 stores each person as a compact ``[canonical, *surface_forms]`` array and
drops confidence entirely:
    ["B. McHugh", "B. Mchugh"]

This walks an archive's ``pages/`` tree, rewrites every ``*.names.json`` success
sidecar in place (atomically), and leaves ``*.names.error.json`` sidecars alone.
It is idempotent: a file already at schema 2 is skipped, so re-running is safe.
Confidence is discarded permanently, so back up ``pages/`` first if unsure
(e.g. ``tar czf names-backup.tgz -C ~/.vt/archive pages``).

Usage:
    python scripts/migrate_sidecars.py [PAGES_DIR] [--dry-run]
    # PAGES_DIR defaults to ~/.vt/archive/pages
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def convert_people(old_people: list) -> list[list[str]]:
    """Convert v1 person objects to v2 ``[canonical, *surface_forms]`` arrays.

    The canonical leads; each verbatim surface form follows, skipping any that
    merely restate the canonical (normalized) and de-duplicating by normalized
    text while preserving first-seen order. Already-converted list entries pass
    through unchanged so the function is safe to apply twice.
    """
    out: list[list[str]] = []
    for person in old_people:
        if isinstance(person, list):  # already v2
            out.append(person)
            continue
        canonical = person["canonical"]
        entry = [canonical]
        seen = {_norm(canonical)}
        for alias in person.get("aliases") or []:
            text = alias["text"] if isinstance(alias, dict) else alias
            key = _norm(text)
            if key in seen:
                continue
            seen.add(key)
            entry.append(text)
        out.append(entry)
    return out


def _is_v2(data: dict) -> bool:
    if data.get("schema") == 2:
        return True
    people = data.get("people") or []
    return bool(people) and all(isinstance(p, list) for p in people)


def migrate_file(path: Path, *, dry_run: bool) -> bool:
    """Rewrite one sidecar to v2. Returns True if it was (or would be) changed."""
    data = json.loads(path.read_text())
    if _is_v2(data) and data.get("schema") == 2:
        return False
    data["people"] = convert_people(data.get("people") or [])
    data["schema"] = 2
    if dry_run:
        return True
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pages_dir", nargs="?",
                    default=str(Path("~/.vt/archive/pages").expanduser()),
                    help="archive pages/ directory (default: ~/.vt/archive/pages)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args(argv)

    root = Path(args.pages_dir)
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    converted = skipped = errored = 0
    for path in root.rglob("*.names.json"):
        if path.name.endswith(".names.error.json"):
            continue
        try:
            if migrate_file(path, dry_run=args.dry_run):
                converted += 1
            else:
                skipped += 1
        except (OSError, ValueError, KeyError, IndexError) as exc:
            errored += 1
            print(f"error: {path}: {exc}", file=sys.stderr)

    verb = "would convert" if args.dry_run else "converted"
    print(f"{verb}: {converted:,}   already v2: {skipped:,}   errors: {errored:,}")
    return 1 if errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
