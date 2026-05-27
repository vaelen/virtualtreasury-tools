# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from vtextract.index.builder import INDEX_RELPATH, _candidates, build
from vtextract.index.db import Fts5Unavailable, IndexDB, SchemaMismatch
from vtextract.index.models import SearchQuery
from vtextract.index.query import search
from vtextract.progress import BuildReporter

_FIELD_CHOICES = ("title", "description", "transcription")


def _resolve_archive(value: str | None) -> Path:
    return Path(value or os.environ.get("VT_ARCHIVE") or "archive")


def _date_bound(value: str | None, *, upper: bool) -> str | None:
    """Normalize a CLI date bound to ISO. A bare year expands to Jan 1 / Dec 31."""
    if value is None:
        return None
    value = value.strip()
    if len(value) == 4 and value.isdigit():
        return f"{value}-12-31" if upper else f"{value}-01-01"
    return value


def _parse_fields(value: str | None) -> tuple[str, ...]:
    if not value:
        return _FIELD_CHOICES
    fields = tuple(f.strip() for f in value.split(",") if f.strip())
    bad = [f for f in fields if f not in _FIELD_CHOICES]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown field(s): {', '.join(bad)}; choose from {', '.join(_FIELD_CHOICES)}"
        )
    return fields


def _is_stale(db: IndexDB, archive: Path) -> bool:
    """True if any source file is new/changed/removed vs the stored fingerprints."""
    fingerprints = db.fingerprints()
    seen: set[str] = set()
    for _kind, relpath, abspath in _candidates(archive):
        seen.add(relpath)
        st = abspath.stat()
        if fingerprints.get(relpath) != (st.st_mtime, st.st_size):
            return True
    return bool(set(fingerprints) - seen)


def _open_for_read(archive: Path) -> IndexDB:
    db_path = archive / INDEX_RELPATH
    if not db_path.exists():
        raise FileNotFoundError(
            f"no index at {db_path}; run `vtindex build --archive {archive}` first."
        )
    return IndexDB(db_path)


def _cmd_build(args) -> int:
    archive = _resolve_archive(args.archive)
    with BuildReporter() as reporter:
        build(archive, rebuild=args.rebuild, reporter=reporter)
    return 0


def _cmd_search(args) -> int:
    archive = _resolve_archive(args.archive)
    query = SearchQuery(
        text=args.query,
        fields=_parse_fields(args.in_fields),
        date_from=_date_bound(args.date_from, upper=False),
        date_to=_date_bound(args.date_to, upper=True),
        date_type=args.date_type,
        volume=args.volume,
        limit=args.limit,
    )
    with _open_for_read(archive) as db:
        if _is_stale(db, archive):
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        results = search(db, query)
    if args.json:
        print(json.dumps([_result_dict(r) for r in results], indent=2))
    else:
        _print_results_table(results)
    return 0 if results else 1


def _cmd_volumes(args) -> int:
    archive = _resolve_archive(args.archive)
    with _open_for_read(archive) as db:
        rows = db.volumes()
    data = [
        {"root_id": r["root_id"], "label": r["label"],
         "reference_code": r["reference_code"], "item_count": r["item_count"]}
        for r in rows
    ]
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for d in data:
            print(f'{d["root_id"]}\t{d["item_count"]:>4}\t{d["label"] or ""}\t'
                  f'{d["reference_code"] or ""}')
    return 0


def _cmd_stats(args) -> int:
    archive = _resolve_archive(args.archive)
    with _open_for_read(archive) as db:
        counts = db.counts()
        stale = _is_stale(db, archive)
        data = {
            "items": counts["items"],
            "volumes": counts["volumes"],
            "pages": counts["pages"],
            "schema_version": db.get_meta("schema_version"),
            "stale": stale,
        }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
    return 0


def _result_dict(r) -> dict:
    return {
        "isadg_id": r.isadg_id,
        "title": r.title,
        "reference_code": r.reference_code,
        "repository": r.repository,
        "content_date": r.content_date,
        "created_date": r.created_date,
        "matched_fields": r.matched_fields,
        "matched_pages": [{"root_id": rt, "page_key": pk} for rt, pk in r.matched_pages],
        "score": r.score,
        "path": r.path,
    }


def _print_results_table(results) -> None:
    if not results:
        print("no matches")
        return
    for r in results:
        fields = ",".join(r.matched_fields) if r.matched_fields else "-"
        print(f'{r.isadg_id}\t{r.content_date or "-"}\t{r.reference_code}\t'
              f'{r.title}\t[{fields}]')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtindex",
        description="Build and search a local index over a vtextract archive.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="(re)build the index from the archive")
    p_build.add_argument("--archive", help="archive dir (default: $VT_ARCHIVE or ./archive)")
    p_build.add_argument("--rebuild", action="store_true", help="discard and rebuild fully")
    p_build.set_defaults(func=_cmd_build)

    p_search = sub.add_parser("search", help="search the index")
    p_search.add_argument("query", nargs="?", help="FTS5 keyword expression (optional)")
    p_search.add_argument("--archive")
    p_search.add_argument("--in", dest="in_fields",
                          help="comma list of: title,description,transcription (default: all)")
    p_search.add_argument("--from", dest="date_from", help="lower date bound (YEAR or ISO)")
    p_search.add_argument("--to", dest="date_to", help="upper date bound (YEAR or ISO)")
    p_search.add_argument("--date-type", choices=("content", "created"), default="content")
    p_search.add_argument("--volume", help="restrict to items referencing this volume root id")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=_cmd_search)

    p_vol = sub.add_parser("volumes", help="list indexed volumes")
    p_vol.add_argument("--archive")
    p_vol.add_argument("--json", action="store_true")
    p_vol.set_defaults(func=_cmd_volumes)

    p_stats = sub.add_parser("stats", help="show index stats and staleness")
    p_stats.add_argument("--archive")
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=_cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, SchemaMismatch, Fts5Unavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except argparse.ArgumentTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
