# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from vtextract.config import load_config
from vtextract.theme import THEMES, Theme, add_theme_args as _add_theme_args, highlight_terms as _highlight_title
from vtextract.index.models import IndexStats, ItemDetail, PageEntry, PageNav, SearchHit, SearchQuery
from vtextract.index.service import IndexService, IndexUnavailable
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



def _page_files_dict(e: PageEntry) -> dict:
    return {
        "root_id": e.root_id,
        "page_key": e.page_key,
        "image": e.image,
        "metadata": e.metadata,
        "transcription": e.transcription,
    }


def _result_dict(h: SearchHit) -> dict:
    return {
        "isadg_id": h.isadg_id,
        "title": h.title,
        "reference_code": h.reference_code,
        "repository": h.repository,
        "content_date": h.content_date,
        "created_date": h.created_date,
        "estimated_date": h.estimated_date,
        "estimated_source": h.estimated_source,
        "matched_fields": h.matched_fields,
        "matched_pages": [{**_page_files_dict(p), "role": p.role} for p in h.matched_pages],
        "score": h.score,
        "path": h.path,
    }


def _page_nav_dict(e: PageEntry | None) -> dict | None:
    if e is None:
        return None
    return {**_page_files_dict(e), "ordinal": e.ordinal, "label": e.label}


def _item_dict(d: ItemDetail) -> dict:
    return {
        "isadg_id": d.isadg_id,
        "reference_code": d.reference_code,
        "title": d.title,
        "description": d.description,
        "repository": d.repository,
        "content_begin": d.content_begin,
        "content_end": d.content_end,
        "created_begin": d.created_begin,
        "created_end": d.created_end,
        "estimated_begin": d.estimated_begin,
        "estimated_end": d.estimated_end,
        "estimated_source": d.estimated_source,
        "pages": [{"root_id": p.root_id, "page_key": p.page_key, "role": p.role} for p in d.pages],
    }


def _cmd_build(args) -> int:
    archive = _resolve_archive(args)
    if not archive.is_dir() or not (
        (archive / "items").is_dir() or (archive / "pages").is_dir()
    ):
        raise FileNotFoundError(
            f"{archive} does not look like a vtextract archive "
            "(no items/ or pages/ directory); nothing to index."
        )
    if args.json_progress:
        from vtextract.progress import JsonBuildReporter
        with JsonBuildReporter() as reporter:
            stats = IndexService.build(archive, rebuild=args.rebuild, reporter=reporter)
    else:
        with BuildReporter() as reporter:
            stats = IndexService.build(archive, rebuild=args.rebuild, reporter=reporter)
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
        offset=args.offset,
    )
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        results = svc.search(query)
    if args.json:
        print(json.dumps([_result_dict(r) for r in results], indent=2))
    else:
        _print_results_table(results, theme=THEMES[args.theme], query=args.query)
    return 0 if results else 1


def _cmd_volumes(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        vols = svc.volumes()
    data = [
        {"root_id": v.root_id, "label": v.label,
         "reference_code": v.reference_code, "item_count": v.item_count,
         "title": v.title}
        for v in vols
    ]
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_volumes_table(vols, theme=THEMES[args.theme])
    return 0


def _build_volumes_table(vols, *, theme: Theme) -> Table:
    table = Table(
        show_header=True,
        header_style=theme.header_style,
        border_style=theme.border_style,
        row_styles=list(theme.row_styles),
    )
    table.add_column("Root ID", no_wrap=True)
    table.add_column("Items", no_wrap=True, justify="right")
    table.add_column("Title")
    table.add_column("Reference", no_wrap=True)
    for v in vols:
        table.add_row(
            v.root_id,
            str(v.item_count),
            v.title or v.label or "-",
            v.reference_code or "-",
        )
    return table


def _print_volumes_table(vols, *, theme: Theme) -> None:
    if not vols:
        print("no volumes")
        return
    table = _build_volumes_table(vols, theme=theme)
    Console(no_color=theme.no_color).print(table)


def _cmd_stats(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        s = svc.stats()
    data = {
        "items": s.items,
        "volumes": s.volumes,
        "pages": s.pages,
        "schema_version": s.schema_version,
        "stale": s.stale,
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
    return 0


def _cmd_page(args) -> int:
    if not args.ref:
        args.parser.print_help(sys.stderr)
        return 2
    archive = _resolve_archive(args)
    if "/" not in args.ref:
        print("error: argument must be <root_id>/<page_key>", file=sys.stderr)
        return 2
    root_id, page_key = args.ref.split("/", 1)
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        nav = svc.page(root_id, page_key)
    if nav is None:
        if args.json:
            print(json.dumps(None))
        else:
            print(f"page not found: {args.ref}")
        return 1
    if nav.current.ordinal is None:
        print("warning: page ordering unavailable (re-extract this volume to "
              "regenerate volume.json).", file=sys.stderr)
    data = {
        "volume": {"root_id": nav.volume.root_id, "title": nav.volume.title},
        "previous": _page_nav_dict(nav.previous),
        "current": _page_nav_dict(nav.current),
        "next": _page_nav_dict(nav.next),
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_page_nav(data, nav.volume.title, theme=THEMES[args.theme])
    return 0


def _cmd_pages(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        rows = svc.pages(args.root_id)
    if not rows:
        if args.json:
            print(json.dumps([]))
        else:
            print(f"no pages for volume {args.root_id}")
        return 1
    enriched = [_page_nav_dict(p) for p in rows]
    if args.json:
        print(json.dumps(enriched, indent=2))
    else:
        _print_page_list(enriched, theme=THEMES[args.theme])
    return 0


def _print_page_list(rows, *, theme: Theme) -> None:
    table = Table(
        show_header=True,
        header_style=theme.header_style,
        border_style=theme.border_style,
        row_styles=list(theme.row_styles),
    )
    table.add_column("#", no_wrap=True, justify="right")
    table.add_column("Page key")
    table.add_column("Label", no_wrap=True)
    table.add_column("Txt", no_wrap=True)
    table.add_column("Img", no_wrap=True)
    for r in rows:
        table.add_row(
            str(r["ordinal"]) if r["ordinal"] is not None else "-",
            r["page_key"],
            r["label"] or "-",
            "•" if r["transcription"] else "",
            "•" if r["image"] else "",
        )
    Console(no_color=theme.no_color).print(table)


def _cmd_item(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        detail = svc.item(args.isadg_id)
    if detail is None:
        if args.json:
            print(json.dumps(None))
        else:
            print(f"item not found: {args.isadg_id}")
        return 1
    item = _item_dict(detail)
    if args.json:
        print(json.dumps(item, indent=2))
    else:
        for k, v in item.items():
            if k == "pages":
                continue
            print(f"{k}: {v if v is not None else '-'}")
        print("pages:")
        for p in item["pages"]:
            print(f"  {p['role']:7s}  {p['root_id']}/{p['page_key']}")
    return 0


def _print_page_nav(nav: dict, title: str | None, *, theme: Theme) -> None:
    table = Table(
        show_header=True,
        title=title or nav["volume"]["root_id"],
        header_style=theme.header_style,
        border_style=theme.border_style,
        row_styles=list(theme.row_styles),
    )
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
    Console(no_color=theme.no_color).print(table)


def _build_results_table(results, *, theme: Theme, query: str | None) -> Table:
    table = Table(
        show_header=True,
        header_style=theme.header_style,
        border_style=theme.border_style,
        row_styles=list(theme.row_styles),
    )
    table.add_column("ID", no_wrap=True)
    table.add_column("Date", no_wrap=True)
    table.add_column("Est.", no_wrap=True)
    table.add_column("Reference", no_wrap=True)
    table.add_column("Title")
    for r in results:
        table.add_row(
            str(r.isadg_id),
            r.content_date or "-",
            r.estimated_date or "-",
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
    p_build.add_argument("--json-progress", action="store_true",
                         help="emit JSONL progress events on stdout instead of "
                              "rich progress on stderr")
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
    p_search.add_argument("--limit", type=int, default=50,
                          help="max results (default 50; 0 or less = no limit)")
    p_search.add_argument("--offset", type=int, default=0,
                          help="skip the first N results (for pagination)")
    p_search.add_argument("--json", action="store_true")
    _add_theme_args(p_search)
    p_search.set_defaults(func=_cmd_search)

    p_vol = sub.add_parser("volumes", help="list indexed volumes")
    _add_archive_args(p_vol)
    p_vol.add_argument("--json", action="store_true")
    _add_theme_args(p_vol)
    p_vol.set_defaults(func=_cmd_volumes)

    p_stats = sub.add_parser("stats", help="show index stats and staleness")
    _add_archive_args(p_stats)
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=_cmd_stats)

    p_page = sub.add_parser("page", help="show a page's previous/next neighbours")
    p_page.add_argument("ref", nargs="?",
                        help="page reference as <root_id>/<page_key>")
    _add_archive_args(p_page)
    p_page.add_argument("--json", action="store_true")
    _add_theme_args(p_page)
    p_page.set_defaults(func=_cmd_page, parser=p_page)

    p_pages = sub.add_parser("pages", help="list every page of a volume")
    p_pages.add_argument("root_id", help="volume root id")
    _add_archive_args(p_pages)
    p_pages.add_argument("--json", action="store_true")
    _add_theme_args(p_pages)
    p_pages.set_defaults(func=_cmd_pages)

    p_item = sub.add_parser("item", help="show one item by isadg id")
    p_item.add_argument("isadg_id", type=int, help="isadg id of the item")
    _add_archive_args(p_item)
    p_item.add_argument("--json", action="store_true")
    _add_theme_args(p_item)
    p_item.set_defaults(func=_cmd_item)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except (FileNotFoundError, IndexUnavailable) as exc:
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
