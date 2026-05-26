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
        if tok in ("--help", "-h") or tok in _SORT_FLAGS:
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
  auth     store credentials in the config file (vtextract auth [username])
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
    if command == "auth":
        return _run_auth(rest)
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
    root_manifest_cache: dict = {}

    completed = 0
    failed = 0
    try:
        for hit in iter_results(client, params, index_db_name=config.index_db_name, page_size=args.page_size):
            isadg_id = int(hit["isadgID"])
            if archive.is_resource_complete(isadg_id):
                print(f"skip {isadg_id} (already complete)")
                continue
            try:
                fetch_resource(
                    client, archive, hit,
                    search_id=search_id,
                    context_pages=args.context_pages,
                    _root_manifest_cache=root_manifest_cache,
                )
                completed += 1
                print(f"done {isadg_id}")
            except Exception as exc:  # noqa: BLE001 - one bad item must not stop the run
                failed += 1
                print(f"FAILED {isadg_id}: {exc!r}", file=sys.stderr)
    finally:
        client.close()

    print(f"finished: {completed} archived, {failed} failed")
    return 1 if failed else 0


def main() -> None:
    sys.exit(run(sys.argv[1:]))
