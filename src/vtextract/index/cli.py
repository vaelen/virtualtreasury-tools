# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from vtextract.config import load_config
from vtextract.index.builder import INDEX_RELPATH, build, is_stale
from vtextract.index.db import Fts5Unavailable, IndexDB, SchemaMismatch
from vtextract.index.models import SearchQuery
from vtextract.index.query import search
from vtextract.progress import BuildReporter

_FIELD_CHOICES = ("title", "description", "transcription")


def _resolve_archive(args) -> Path:
    """Archive dir: ``--archive`` if given, else the config file's ``archive``."""
    if args.archive:
        return Path(args.archive)
    config = load_config(Path(args.config) if args.config else None)
    return config.archive


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



def _open_for_read(archive: Path) -> IndexDB:
    db_path = archive / INDEX_RELPATH
    if not db_path.exists():
        raise FileNotFoundError(
            f"no index at {db_path}; run `vtindex build --archive {archive}` first."
        )
    return IndexDB(db_path)


def _cmd_build(args) -> int:
    archive = _resolve_archive(args)
    if not archive.is_dir() or not (
        (archive / "items").is_dir() or (archive / "pages").is_dir()
    ):
        raise FileNotFoundError(
            f"{archive} does not look like a vtextract archive "
            "(no items/ or pages/ directory); nothing to index."
        )
    with BuildReporter() as reporter:
        stats = build(archive, rebuild=args.rebuild, reporter=reporter)
    if stats.skipped and (stats.added + stats.updated + stats.unchanged) == 0:
        print(
            f"error: indexed nothing; {stats.skipped} source file(s) were skipped "
            "due to parse errors.",
            file=sys.stderr,
        )
        return 2
    return 0


def _cmd_search(args) -> int:
    archive = _resolve_archive(args)
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
        if is_stale(db, archive):
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        results = search(db, query)
    if args.json:
        print(json.dumps([_result_dict(r, archive) for r in results], indent=2))
    else:
        _print_results_table(results, theme=THEMES[args.theme], query=args.query)
    return 0 if results else 1


def _cmd_volumes(args) -> int:
    archive = _resolve_archive(args)
    with _open_for_read(archive) as db:
        vols = db.volumes()
    data = [
        {"root_id": v.root_id, "label": v.label,
         "reference_code": v.reference_code, "item_count": v.item_count,
         "title": v.title}
        for v in vols
    ]
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for d in data:
            print(f'{d["root_id"]}\t{d["item_count"]:>4}\t{d["title"] or d["label"] or ""}\t'
                  f'{d["reference_code"] or ""}')
    return 0


def _cmd_stats(args) -> int:
    archive = _resolve_archive(args)
    with _open_for_read(archive) as db:
        counts = db.counts()
        stale = is_stale(db, archive)
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


def _page_file(page_dir: Path, name: str) -> str | None:
    """Absolute path to a page file, or None if it isn't in the archive."""
    path = page_dir / name
    return str(path.resolve()) if path.exists() else None


def _page_dict(archive: Path, root_id: str, page_key: str) -> dict:
    # Page store layout (see archive.py): image is `{page_key}`, transcription
    # is `{page_key}.txt`, annotations/metadata is `{page_key}.json`.
    page_dir = archive / "pages" / root_id
    return {
        "root_id": root_id,
        "page_key": page_key,
        "image": _page_file(page_dir, page_key),
        "metadata": _page_file(page_dir, f"{page_key}.json"),
        "transcription": _page_file(page_dir, f"{page_key}.txt"),
    }


def _result_dict(r, archive: Path) -> dict:
    return {
        "isadg_id": r.isadg_id,
        "title": r.title,
        "reference_code": r.reference_code,
        "repository": r.repository,
        "content_date": r.content_date,
        "created_date": r.created_date,
        "matched_fields": r.matched_fields,
        "matched_pages": [_page_dict(archive, rt, pk) for rt, pk in r.matched_pages],
        "score": r.score,
        "path": r.path,
    }


def _page_nav_dict(archive: Path, row: dict | None) -> dict | None:
    """Page navigation entry: file paths (_page_dict) plus ordinal and label."""
    if row is None:
        return None
    d = _page_dict(archive, row["root_id"], row["page_key"])
    d["ordinal"] = row["ordinal"]
    d["label"] = row["label"]
    return d


def _cmd_page(args) -> int:
    archive = _resolve_archive(args)
    if "/" not in args.ref:
        print("error: argument must be <root_id>/<page_key>", file=sys.stderr)
        return 2
    root_id, page_key = args.ref.split("/", 1)
    with _open_for_read(archive) as db:
        if is_stale(db, archive):
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        current = db.get_page(root_id, page_key)
        if current is None:
            if args.json:
                print(json.dumps(None))
            else:
                print(f"page not found: {args.ref}")
            return 1
        ordinal = current["ordinal"]
        if ordinal is None:
            print("warning: page ordering unavailable (re-extract this volume to "
                  "regenerate volume.json).", file=sys.stderr)
            previous = nxt = None
        else:
            previous = db.page_at_ordinal(root_id, ordinal - 1)
            nxt = db.page_at_ordinal(root_id, ordinal + 1)
        volume = db.volume(root_id) or {"root_id": root_id, "title": None}
    nav = {
        "volume": {"root_id": root_id, "title": volume.get("title")},
        "previous": _page_nav_dict(archive, previous),
        "current": _page_nav_dict(archive, current),
        "next": _page_nav_dict(archive, nxt),
    }
    if args.json:
        print(json.dumps(nav, indent=2))
    else:
        _print_page_nav(nav, volume.get("title"))
    return 0


def _print_page_nav(nav: dict, title: str | None) -> None:
    table = Table(show_header=True, title=title or nav["volume"]["root_id"])
    table.add_column("Position", no_wrap=True)
    table.add_column("Ordinal", no_wrap=True)
    table.add_column("Label", no_wrap=True)
    table.add_column("Image")
    for position in ("previous", "current", "next"):
        entry = nav[position]
        if entry is None:
            continue
        table.add_row(
            position,
            str(entry["ordinal"]) if entry["ordinal"] is not None else "-",
            entry["label"] or "-",
            entry["image"] or entry["page_key"],
        )
    Console().print(table)


@dataclass(frozen=True)
class Theme:
    """A color scheme for the search results table."""

    header_style: str
    border_style: str
    match_style: str  # applied to query keywords found in the Title
    row_styles: tuple[str, ...] = field(default_factory=tuple)
    no_color: bool = False


# `--dark` is the default. Each adds a touch of color tuned for a terminal
# background; `--bw` keeps a neutral no-color-fill scheme and `--plain` is
# unstyled for piping or color-averse terminals.
THEMES: dict[str, Theme] = {
    "dark": Theme(
        header_style="bold cyan", border_style="grey42",
        match_style="bold yellow", row_styles=("", "on grey19"),
    ),
    "light": Theme(
        header_style="bold blue", border_style="grey50",
        match_style="black on yellow", row_styles=("", "on grey85"),
    ),
    "bw": Theme(header_style="bold", border_style="", match_style="reverse"),
    "plain": Theme(header_style="none", border_style="", match_style="", no_color=True),
}

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _highlight_title(title: str, query: str | None, style: str) -> Text:
    """Return the title as rich Text with query keywords styled.

    Keywords are the word tokens of the raw query (mirroring the whitespace
    tokenization the FTS index uses); a title word is highlighted when it
    equals one of them, case-insensitively. No query or no style → no spans.
    """
    text = Text(title)
    if not query or not style:
        return text
    terms = {m.group(0).lower() for m in _WORD_RE.finditer(query)}
    if not terms:
        return text
    for m in _WORD_RE.finditer(title):
        if m.group(0).lower() in terms:
            text.stylize(style, m.start(), m.end())
    return text


def _build_results_table(results, *, theme: Theme, query: str | None) -> Table:
    table = Table(
        show_header=True,
        header_style=theme.header_style,
        border_style=theme.border_style,
        row_styles=list(theme.row_styles),
    )
    table.add_column("ID", no_wrap=True)
    table.add_column("Date", no_wrap=True)
    table.add_column("Reference", no_wrap=True)
    table.add_column("Title")
    for r in results:
        table.add_row(
            str(r.isadg_id),
            r.content_date or "-",
            r.reference_code,
            _highlight_title(r.title, query, theme.match_style),
        )
    return table


def _print_results_table(results, *, theme: Theme, query: str | None) -> None:
    if not results:
        print("no matches")
        return
    table = _build_results_table(results, theme=theme, query=query)
    Console(no_color=theme.no_color).print(table)


_ARCHIVE_HELP = "archive dir (default: the config file's archive)"


def _add_archive_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--archive`` / ``--config`` options to a subparser."""
    parser.add_argument("--archive", help=_ARCHIVE_HELP)
    parser.add_argument("--config", help="Config file path (default ~/.vt/vt.toml).")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtindex",
        description="Build and search a local index over a vtextract archive.",
    )
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="(re)build the index from the archive")
    _add_archive_args(p_build)
    p_build.add_argument("--rebuild", action="store_true", help="discard and rebuild fully")
    p_build.set_defaults(func=_cmd_build)

    p_search = sub.add_parser("search", help="search the index")
    p_search.add_argument("query", nargs="?", help="FTS5 keyword expression (optional)")
    _add_archive_args(p_search)
    p_search.add_argument("--in", dest="in_fields",
                          help="comma list of: title,description,transcription (default: all)")
    p_search.add_argument("--from", dest="date_from", help="lower date bound (YEAR or ISO)")
    p_search.add_argument("--to", dest="date_to", help="upper date bound (YEAR or ISO)")
    p_search.add_argument("--date-type", choices=("content", "created"), default="content")
    p_search.add_argument("--volume", help="restrict to items referencing this volume root id")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--json", action="store_true")
    theme = p_search.add_mutually_exclusive_group()
    theme.add_argument("--dark", dest="theme", action="store_const", const="dark",
                       help="dark-mode color scheme (default)")
    theme.add_argument("--light", dest="theme", action="store_const", const="light",
                       help="light-mode color scheme")
    theme.add_argument("--bw", dest="theme", action="store_const", const="bw",
                       help="neutral black-and-white scheme (no color fills)")
    theme.add_argument("--plain", dest="theme", action="store_const", const="plain",
                       help="disable all colors")
    p_search.set_defaults(func=_cmd_search, theme="dark")

    p_vol = sub.add_parser("volumes", help="list indexed volumes")
    _add_archive_args(p_vol)
    p_vol.add_argument("--json", action="store_true")
    p_vol.set_defaults(func=_cmd_volumes)

    p_stats = sub.add_parser("stats", help="show index stats and staleness")
    _add_archive_args(p_stats)
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=_cmd_stats)

    p_page = sub.add_parser("page", help="show a page's previous/next neighbours")
    p_page.add_argument("ref", help="page reference as <root_id>/<page_key>")
    _add_archive_args(p_page)
    p_page.add_argument("--json", action="store_true")
    p_page.set_defaults(func=_cmd_page)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except (FileNotFoundError, SchemaMismatch, Fts5Unavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as exc:
        print(f"error: invalid query: {exc}", file=sys.stderr)
        return 2
    except argparse.ArgumentTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
