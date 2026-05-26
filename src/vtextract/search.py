from __future__ import annotations

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
