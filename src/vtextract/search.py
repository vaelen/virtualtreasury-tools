# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

# Pagination params are owned by the tool's pager, not taken from the user's URL.
_PAGINATION_KEYS = {"pageNumberInt", "totalElementsInt"}


def parse_search_url(url: str) -> dict[str, str]:
    """Extract doc_search query parameters from a /search-results URL.

    Multi-valued params collapse to their first value (the site uses single
    values for these keys).
    """
    query = parse_qs(urlparse(url).query, keep_blank_values=True)
    return {
        key: values[0]
        for key, values in query.items()
        if key not in _PAGINATION_KEYS and values
    }


def build_body(
    params: dict[str, str],
    *,
    page_number: int,
    page_size: int,
    index_db_name: str,
) -> dict:
    """Construct the JSON body for POST /IR_REST_V2/webapi/doc_search."""
    return {
        "indexDBName": index_db_name,
        **params,
        "pageNumberInt": page_number,
        "totalElementsInt": page_size,
    }


SEARCH_PATH = "/IR_REST_V2/webapi/doc_search"


def iter_results(
    client,
    params: dict[str, str],
    *,
    index_db_name: str,
    page_size: int = 100,
) -> Iterator[dict]:
    """Yield every resource record across all pages of a doc_search query."""
    page_number = 0
    seen = 0
    while True:
        body = build_body(
            params,
            page_number=page_number,
            page_size=page_size,
            index_db_name=index_db_name,
        )
        response = client.post_json(SEARCH_PATH, body)
        records = response.get("resultInfoList", [])
        total = response.get("generalInfo", {}).get("totalDocs", 0)
        for record in records:
            yield record
        seen += len(records)
        if not records or seen >= total:
            break
        page_number += 1
