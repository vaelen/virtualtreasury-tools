# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

import httpx

from vtextract.archive import Archive
from vtextract.client import Client
from vtextract.config import default_config_path, load_config, make_token, set_token
from vtextract.fetcher import fetch_resource
from vtextract.models import BOOST_FOR_FIELD, FIELD_MAP, OPERANDS, Filter, SearchCriteria
from vtextract.progress import JsonFetchReporter, Reporter
from vtextract.search import criteria_to_params, iter_results


def _make_transport() -> httpx.BaseTransport | None:
    """Seam for tests to inject a MockTransport. Returns None in production."""
    return None


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def _nonneg_int(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


# Global options that consume the following token as their value.
_VALUE_OPTS = {"--out", "--config", "--start", "--end", "--context-pages", "--page-size"}
# Zero-arg global flags handled by argparse (result ordering).
_SORT_FLAGS = {"--relevance", "--newest", "--oldest"}
# Field flags: "--title" -> "title" key into FIELD_MAP.
_FIELD_FLAGS = {f"--{name}": name for name in FIELD_MAP}
# Operand flags: "--all" -> "all" key into OPERANDS.
_OPERAND_FLAGS = {f"--{name}": name for name in OPERANDS}
# Zero-arg boolean global flags handled by argparse.
_BOOL_FLAGS = {"--refresh", "--images", "--json-progress"}

_EPILOG = """\
search criteria (parsed positionally, in order):
  field flags     --keyword (default), --title, --transcription, --creator,
                  --ref, --person, --place
  operand flags   --all (default), --any, --none, --exact
  keywords        positional words; those after a field/operand flag form one
                  search clause, e.g. `--title --all memorial houston`
  Multiple clauses combine: each field flag starts a new clause and resets the
  operand to --all. --person/--place rank by knowledge-graph entity (the last
  one wins). The backend also has a searchDocumentRepositoryNameList filter,
  but its valid values are unknown, so there is no flag for it.

example:
  vtextract --title --all memorial houston --transcription --any castle \\
            --place --exact Dublin --start 1700-01-01 --newest --out ./archive
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtextract search",
        description="Download resources matching a virtualtreasury.ie search.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out",
        help="Output archive directory (defaults to the config file's archive).",
    )
    parser.add_argument(
        "--config", help="Config file path (default ~/.vt/vt.toml)."
    )
    parser.add_argument("--start", help="Start of content date range (yyyy-mm-dd).")
    parser.add_argument("--end", help="End of content date range (yyyy-mm-dd).")
    sort = parser.add_mutually_exclusive_group()
    sort.add_argument(
        "--relevance", dest="sorting", action="store_const", const="relevance",
        default="relevance", help="Order results by relevance (default).",
    )
    sort.add_argument(
        "--newest", dest="sorting", action="store_const", const="descending",
        help="Order results newest content date first.",
    )
    sort.add_argument(
        "--oldest", dest="sorting", action="store_const", const="ascending",
        help="Order results oldest content date first.",
    )
    parser.add_argument(
        "--context-pages", type=_nonneg_int, default=1,
        help="Neighbouring physical pages to also fetch per page (default 1).",
    )
    parser.add_argument(
        "--page-size", type=_positive_int, default=100,
        help="doc_search page size (default 100).",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch metadata for matched resources (and HEAD-verify images "
        "when --images is set), even if already archived.",
    )
    parser.add_argument(
        "--images", action="store_true",
        help="Download full-resolution page images (default: transcriptions "
        "and metadata only).",
    )
    parser.add_argument(
        "--json-progress", action="store_true",
        help="emit JSONL progress events on stdout instead of "
        "rich progress on stderr",
    )
    return parser


def split_and_group(
    argv: list[str], parser: argparse.ArgumentParser
) -> tuple[list[str], SearchCriteria]:
    """Split argv into argparse global tokens and a SearchCriteria.

    A single left-to-right pass, so interleaved keyword position is preserved:
    global options are routed to argparse; field/operand flags and keywords are
    grouped into filters. start/end/sorting come back from argparse and are
    filled in by run().
    """
    global_tokens: list[str] = []
    filters: list[Filter] = []
    cur_field: str | None = None
    cur_operand = "ALL"
    cur_keywords: list[str] = []
    boost: str | None = None

    def flush() -> None:
        nonlocal cur_keywords
        if cur_keywords:
            filters.append(Filter(cur_field or "all", cur_operand, cur_keywords))
        cur_keywords = []

    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("--help", "-h") or tok in _SORT_FLAGS or tok in _BOOL_FLAGS:
            global_tokens.append(tok)
            i += 1
        elif tok in _VALUE_OPTS:
            if i + 1 >= len(argv):
                parser.error(f"argument {tok}: expected one argument")
            global_tokens += [tok, argv[i + 1]]
            i += 2
        elif tok in _FIELD_FLAGS:
            flush()
            name = _FIELD_FLAGS[tok]
            cur_field = FIELD_MAP[name]
            cur_operand = "ALL"
            if name in BOOST_FOR_FIELD:
                boost = BOOST_FOR_FIELD[name]
            i += 1
        elif tok in _OPERAND_FLAGS:
            cur_operand = OPERANDS[_OPERAND_FLAGS[tok]]
            i += 1
        elif tok.startswith("-"):
            parser.error(f"unrecognized arguments: {tok}")
        else:
            cur_keywords.append(tok)
            i += 1
    flush()
    return global_tokens, SearchCriteria(filters=filters, boost=boost)


_USAGE = """\
usage: vtextract <command> [options]

commands:
  search   download resources matching a search (vtextract search --help)
  get      download resources by reference code or id (vtextract get --help)
  auth     store credentials in the config file (vtextract auth [username])
  refresh  re-fetch metadata and verify images for the whole archive
"""


def run(argv: list[str]) -> int:
    """Dispatch to a subcommand. No command (or unknown) prints help."""
    if not argv or argv[0] in ("-h", "--help"):
        out = sys.stdout if argv else sys.stderr
        print(_USAGE, end="", file=out)
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    if command == "search":
        return _run_search(rest)
    if command == "get":
        return _run_get(rest)
    if command == "auth":
        return _run_auth(rest)
    if command == "refresh":
        return _run_refresh(rest)
    print(f"unknown command: {command}\n", file=sys.stderr)
    print(_USAGE, end="", file=sys.stderr)
    return 2


def _run_auth(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="vtextract auth",
        description="Store the basic-auth credential in the config file.",
    )
    parser.add_argument(
        "username",
        nargs="?",
        help="If given, prompt for a password and store the computed digest. "
        "Otherwise prompt for the base64 token directly.",
    )
    parser.add_argument("--config", help="Config file path (default ~/.vt/vt.toml).")
    args = parser.parse_args(argv)
    path = Path(args.config) if args.config else default_config_path()

    if args.username:
        password = getpass.getpass("Password: ")
        token = make_token(args.username, password)
    else:
        token = getpass.getpass("Basic auth token (base64): ").strip()

    set_token(path, token)
    print(f"Saved credentials to {path}")
    return 0


def _run_search(argv: list[str]) -> int:
    parser = build_parser()
    global_tokens, criteria = split_and_group(argv, parser)
    args = parser.parse_args(global_tokens)
    criteria.start = args.start
    criteria.end = args.end
    criteria.sorting = args.sorting
    if not criteria.filters:
        parser.error("no search criteria: pass at least one keyword")

    config = load_config(Path(args.config) if args.config else None)
    if config.auth_header is None:
        print("No credentials configured. Run `vtextract auth`.", file=sys.stderr)
        return 2

    client = Client(
        base_url=config.base_url,
        auth_header=config.auth_header,
        user_agent=config.user_agent,
        transport=_make_transport(),
        delay=config.delay,
        max_retries=config.max_retries,
    )
    archive = Archive(args.out if args.out else config.archive)
    params = criteria_to_params(criteria)
    search_id = json.dumps(params, sort_keys=True)  # stable id; dedupes re-runs

    reporter = JsonFetchReporter() if args.json_progress else Reporter()
    hits = iter_results(
        client, params, index_db_name=config.index_db_name,
        page_size=args.page_size, on_total=reporter.set_total,
    )
    completed, failed = _extract(
        client, archive, hits, search_id=search_id,
        context_pages=args.context_pages, reporter=reporter,
        refresh=args.refresh, images=args.images,
    )
    return 1 if failed else 0


def _extract(client, archive, hits, *, search_id: str, context_pages: int,
             reporter=None, refresh: bool = False, images: bool = False,
             total: tuple[int, str] | None = None) -> tuple[int, int]:
    """Run the shared per-resource fetch loop, returning (completed, failed).

    Owns the root-manifest cache and the client's lifetime; one bad resource is
    logged and skipped so it never aborts the run. Progress and status output
    go through ``reporter``. ``total=(n, noun)`` is announced from inside the
    reporter's context so JSON reporters emit ``start`` before any other event.
    """
    if reporter is None:
        reporter = Reporter()
    root_manifest_cache: dict = {}
    verified: set[str] = set()
    vcounts: dict[str, int] = {}
    flagged: list[str] = []

    def _on_verify(outcome: str, path: str) -> None:
        vcounts[outcome] = vcounts.get(outcome, 0) + 1
        if outcome in ("mismatch", "unverified"):
            flagged.append(path)

    completed = 0
    failed = 0
    try:
        with reporter:
            if total is not None:
                reporter.set_total(total[0], noun=total[1])
            for hit in hits:
                # A numeric isadgID lets us dedupe before any request; a reference-code
                # hit only learns its id once fetch_resource fetches the detail.
                raw_id = hit.get("isadgID")
                isadg_id = int(raw_id) if raw_id is not None and str(raw_id).isdigit() else None
                if (not refresh) and isadg_id is not None and archive.is_resource_complete(isadg_id, want_images=images):
                    reporter.skip(isadg_id)
                    continue
                label = isadg_id if isadg_id is not None else hit.get("displayReferenceCode", "?")
                reporter.start_item(label)
                try:
                    record = fetch_resource(
                        client, archive, hit,
                        search_id=search_id,
                        context_pages=context_pages,
                        images=images,
                        on_item_start=reporter.item_pages,
                        on_page=reporter.page_done,
                        refresh=refresh,
                        on_verify=_on_verify,
                        _root_manifest_cache=root_manifest_cache,
                        _verified_pages=verified,
                    )
                    completed += 1
                    reporter.item_done(record.isadg_id)
                except Exception as exc:  # noqa: BLE001 - one bad item must not stop the run
                    failed += 1
                    reporter.fail(label, exc)
    finally:
        client.close()

    if refresh:
        reporter.verify_summary(vcounts, flagged)
    reporter.finish(completed, failed)
    return completed, failed


def _run_get(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="vtextract get",
        description="Download resources by reference code or isadgID. Reference "
        "codes may use spaces or slashes (TNA SO 1/14); both become dashes.",
    )
    parser.add_argument(
        "identifiers", nargs="+",
        help="Reference codes (e.g. TNA-SO-1-14) and/or numeric isadgIDs.",
    )
    parser.add_argument(
        "--out", help="Output archive directory (defaults to the config file's archive)."
    )
    parser.add_argument("--config", help="Config file path (default ~/.vt/vt.toml).")
    parser.add_argument(
        "--context-pages", type=_nonneg_int, default=1,
        help="Neighbouring physical pages to also fetch per page (default 1).",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch metadata for the given resources (and HEAD-verify images "
        "when --images is set), even if already archived.",
    )
    parser.add_argument(
        "--images", action="store_true",
        help="Download full-resolution page images (default: transcriptions "
        "and metadata only).",
    )
    parser.add_argument(
        "--json-progress", action="store_true",
        help="emit JSONL progress events on stdout instead of "
        "rich progress on stderr",
    )
    args = parser.parse_args(argv)

    config = load_config(Path(args.config) if args.config else None)
    if config.auth_header is None:
        print("No credentials configured. Run `vtextract auth`.", file=sys.stderr)
        return 2

    client = Client(
        base_url=config.base_url,
        auth_header=config.auth_header,
        user_agent=config.user_agent,
        transport=_make_transport(),
        delay=config.delay,
        max_retries=config.max_retries,
    )
    archive = Archive(args.out if args.out else config.archive)

    # Each identifier becomes a thin hit carrying only the lookup key: a numeric
    # argument is an isadgID, anything else is a reference code. _extract fetches
    # the detail (by id or by reference code) and builds all output from it.
    hits = [
        {"isadgID": int(token)} if token.isdigit() else {"displayReferenceCode": token}
        for token in args.identifiers
    ]
    reporter = JsonFetchReporter() if args.json_progress else Reporter()
    completed, failed = _extract(
        client, archive, hits, search_id="get",
        context_pages=args.context_pages, reporter=reporter,
        refresh=args.refresh, images=args.images,
        total=(len(hits), "resources"),
    )
    return 1 if failed else 0


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _prompt_yes_no(message: str) -> bool:
    try:
        return input(message).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _run_refresh(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="vtextract refresh",
        description="Re-fetch metadata for every archived item. With --images, "
        "also HEAD-verifies every image against the server.",
    )
    parser.add_argument(
        "--out", help="Archive directory (defaults to the config file's archive)."
    )
    parser.add_argument("--config", help="Config file path (default ~/.vt/vt.toml).")
    parser.add_argument(
        "--context-pages", type=_nonneg_int, default=1,
        help="Neighbouring physical pages to also consider per page (default 1).",
    )
    parser.add_argument(
        "--images", action="store_true",
        help="Also HEAD-verify and re-download images (default: metadata and "
        "transcriptions only).",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip the confirmation prompt.",
    )
    parser.add_argument(
        "--json-progress", action="store_true",
        help="emit JSONL progress events on stdout instead of "
        "rich progress on stderr",
    )
    args = parser.parse_args(argv)

    config = load_config(Path(args.config) if args.config else None)
    if config.auth_header is None:
        print("No credentials configured. Run `vtextract auth`.", file=sys.stderr)
        return 2

    archive = Archive(args.out if args.out else config.archive)
    items_dir = archive.root / "items"
    hits = [
        {"isadgID": int(meta.parent.name)}
        for meta in sorted(items_dir.glob("*/metadata.json"))
        if meta.parent.name.isdigit()
    ]
    if not hits:
        print(f"no items to refresh in {archive.root}", file=sys.stderr)
        return 0

    if not args.yes:
        if not _stdin_is_tty():
            print(
                "refusing to run refresh without confirmation; re-run with --yes",
                file=sys.stderr,
            )
            return 2
        if args.images:
            prompt_detail = (
                "metadata and HEAD-verifies every image against the server"
            )
        else:
            prompt_detail = (
                "metadata and backfills any missing transcriptions; images on "
                "disk are left untouched"
            )
        if not _prompt_yes_no(
            f"Refresh {len(hits)} item(s) in {archive.root}? This re-fetches "
            f"{prompt_detail}. [y/N] "
        ):
            print("aborted.", file=sys.stderr)
            return 0

    client = Client(
        base_url=config.base_url,
        auth_header=config.auth_header,
        user_agent=config.user_agent,
        transport=_make_transport(),
        delay=config.delay,
        max_retries=config.max_retries,
    )
    reporter = JsonFetchReporter() if args.json_progress else Reporter()
    completed, failed = _extract(
        client, archive, hits, search_id="refresh",
        context_pages=args.context_pages, reporter=reporter, refresh=True,
        images=args.images, total=(len(hits), "items"),
    )
    return 1 if failed else 0


def main() -> None:
    sys.exit(run(sys.argv[1:]))
