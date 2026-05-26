# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import sys

import httpx

from vtextract.archive import Archive
from vtextract.client import Client
from vtextract.config import load_config
from vtextract.fetcher import fetch_resource
from vtextract.search import iter_results, parse_search_url


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtextract",
        description="Download resources matching a virtualtreasury.ie search.",
    )
    parser.add_argument("search_url", help="A /search-results URL to archive.")
    parser.add_argument("--out", required=True, help="Output archive directory.")
    parser.add_argument(
        "--context-pages", type=_nonneg_int, default=1,
        help="Neighbouring physical pages to also fetch per page (default 1).",
    )
    parser.add_argument(
        "--page-size", type=_positive_int, default=100,
        help="doc_search page size (default 100).",
    )
    return parser


def run(argv: list[str], *, env: dict[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(env)

    client = Client(
        base_url=config.base_url,
        auth_header=config.auth_header,
        user_agent=config.user_agent,
        transport=_make_transport(),
        delay=config.delay,
        max_retries=config.max_retries,
    )
    archive = Archive(args.out)
    params = parse_search_url(args.search_url)
    search_id = args.search_url
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
