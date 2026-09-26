#!/usr/bin/env python3
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT
"""Snapshot the archive's name-extraction status and diff it against a baseline.

Each `.jpg.txt` page is classified by which sidecar exists:
  successful  -> {page}.names.json present
  errored     -> {page}.names.error.json present (and no success sidecar)
  not-run     -> neither

A baseline directory holds three sorted lists (`successful.txt`, `not-run.txt`,
`errored.txt`) as written by this script's --snapshot-to (or the original
baseline snapshot). Comparing a fresh scan against that baseline prints the
before->after transition matrix and the headline numbers — recovered (was
errored, now ok), regressed (was ok, now errored), newly-run, still-failed.

Usage:
  # capture the BEFORE baseline
  python scripts/compare_names_status.py --snapshot-to ~/.vt/baseline-2026-06-07

  # later, after re-running extraction: capture AFTER and diff vs baseline
  python scripts/compare_names_status.py \
      --baseline ~/.vt/baseline-2026-06-07 \
      --snapshot-to ~/.vt/after-2026-06-08 \
      --out ~/.vt/compare-2026-06-08

  # diff only, no files written
  python scripts/compare_names_status.py --baseline ~/.vt/baseline-2026-06-07
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

STATUSES = ("successful", "not-run", "errored")
_TXT = ".jpg.txt"


def scan(pages_root: Path) -> dict[str, str]:
    """Map each page key ({root_id}/{page_key}.jpg) -> status."""
    status: dict[str, str] = {}
    root = str(pages_root)
    for dp, _dirs, fs in os.walk(root):
        rel = os.path.relpath(dp, root)
        files = set(fs)
        for f in fs:
            if not f.endswith(_TXT):
                continue
            base = f[: -len(".txt")]  # e.g. NAME.jpg
            page = base if rel == "." else os.path.join(rel, base)
            if base + ".names.json" in files:
                status[page] = "successful"
            elif base + ".names.error.json" in files:
                status[page] = "errored"
            else:
                status[page] = "not-run"
    return status


def write_snapshot(status: dict[str, str], outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for st in STATUSES:
        rows = sorted(p for p, s in status.items() if s == st)
        text = "\n".join(rows) + ("\n" if rows else "")
        (outdir / f"{st}.txt").write_text(text)


def load_snapshot(d: Path) -> dict[str, str]:
    status: dict[str, str] = {}
    for st in STATUSES:
        f = d / f"{st}.txt"
        if not f.exists():
            raise SystemExit(f"error: baseline missing {f}")
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                status[line] = st
    return status


def compare(before: dict[str, str], after: dict[str, str], out: Path | None) -> None:
    pages = sorted(set(before) | set(after))
    GONE, NEW = "(absent)", "(absent)"
    matrix: dict[tuple[str, str], list[str]] = {}
    for p in pages:
        b = before.get(p, GONE)
        a = after.get(p, NEW)
        matrix.setdefault((b, a), []).append(p)

    def n(b, a):
        return len(matrix.get((b, a), ()))

    print(f"baseline pages: {len(before):,}   current pages: {len(after):,}\n")
    print("transition matrix (before -> after):")
    befores = STATUSES + (GONE,)
    afters = STATUSES + (NEW,)
    hdr = "".join(f"{a:>12}" for a in afters)
    print(f"{'before|after':>14}{hdr}")
    for b in befores:
        row = "".join(f"{n(b, a):>12,}" for a in afters)
        print(f"{b:>14}{row}")

    recovered = matrix.get(("errored", "successful"), [])
    still_failed = matrix.get(("errored", "errored"), [])
    regressed = matrix.get(("successful", "errored"), [])
    lost = matrix.get(("successful", "not-run"), [])
    newly_ok = matrix.get(("not-run", "successful"), [])
    newly_failed = matrix.get(("not-run", "errored"), [])
    still_pending = matrix.get(("not-run", "not-run"), [])

    print("\nheadlines:")
    print(f"  recovered (errored -> successful):   {len(recovered):>7,}")
    print(f"  still failing (errored -> errored):  {len(still_failed):>7,}")
    print(f"  regressed (successful -> errored):   {len(regressed):>7,}")
    print(f"  lost sidecar (successful -> not-run):{len(lost):>7,}")
    print(f"  newly run ok (not-run -> successful):{len(newly_ok):>7,}")
    print(f"  newly failed (not-run -> errored):   {len(newly_failed):>7,}")
    print(f"  still pending (not-run -> not-run):  {len(still_pending):>7,}")

    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        named = {
            "recovered.txt": recovered, "still-failed.txt": still_failed,
            "regressed.txt": regressed, "lost-sidecar.txt": lost,
            "newly-run-ok.txt": newly_ok, "newly-failed.txt": newly_failed,
            "still-pending.txt": still_pending,
        }
        for name, rows in named.items():
            (out / name).write_text("\n".join(sorted(rows)) + ("\n" if rows else ""))
        print(f"\nwrote transition lists to {out}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", default=str(Path("~/.vt/archive").expanduser()),
                    help="archive root (its pages/ is scanned; default ~/.vt/archive)")
    ap.add_argument("--baseline", help="baseline snapshot dir to diff against")
    ap.add_argument("--snapshot-to", help="also write the current scan here")
    ap.add_argument("--out", help="write transition lists here (with --baseline)")
    args = ap.parse_args(argv)

    pages = Path(args.archive) / "pages"
    if not pages.is_dir():
        print(f"error: no pages/ under {args.archive}")
        return 2

    current = scan(pages)
    counts = {st: sum(1 for s in current.values() if s == st) for st in STATUSES}
    print(f"current: successful={counts['successful']:,}  "
          f"not-run={counts['not-run']:,}  errored={counts['errored']:,}  "
          f"(total {len(current):,})\n")

    if args.snapshot_to:
        write_snapshot(current, Path(args.snapshot_to))
        print(f"snapshot written to {args.snapshot_to}\n")

    if args.baseline:
        before = load_snapshot(Path(args.baseline))
        compare(before, current, Path(args.out) if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
