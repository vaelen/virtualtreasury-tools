# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Free-text year/year-range parser for the index's estimated_date fallback.

Used when a record has no catalogued dates in its metadata but its volume or
own title carries a year (e.g. "Vol. 2: 1794-1801"). Pure functions; no I/O.
"""

from __future__ import annotations

import re
from typing import Iterable

_YEAR_MIN = 1500
_YEAR_MAX = 1999

# A 4-digit year guarded against being part of a larger token. Left/right
# guards reject `\w` (letters/digits/_) and `/` so we don't catch catalogue
# fragments like `MS1954` or `1954/RoD`.
_PATTERN = re.compile(
    r"(?<![\w/])"
    r"(1[5-9]\d{2})"
    r"(?:\s*[-–—]\s*(\d{2,4}))?"
    r"(?![\w/])"
)


def parse_year_range(
    text: str, *, ignore: Iterable[str] = ()
) -> tuple[str | None, str | None]:
    """Return (begin_iso, end_iso) for the first year/range in text, else (None, None).

    Single years return (YYYY-01-01, YYYY-12-31). Ranges return the outer
    span. Two-digit trailing groups apply century rollover (`1708-45` →
    1745); the rollover only crosses a century boundary when the begin
    year is in the latter half of its century (`1799-02` → 1802, but
    `1745-08` falls back to the single year 1745).

    Substrings in `ignore` are removed from `text` case-insensitively
    before scanning, so reference codes embedded in a title don't
    contribute spurious years.
    """
    if not text:
        return (None, None)
    cleaned = _strip_ignored(text, ignore)
    for m in _PATTERN.finditer(cleaned):
        begin = int(m.group(1))
        if not (_YEAR_MIN <= begin <= _YEAR_MAX):
            continue
        suffix = m.group(2)
        if suffix is None:
            return _single(begin)
        end = _resolve_end(begin, int(suffix), len(suffix))
        if end is None:
            return _single(begin)
        return _range(begin, end)
    return (None, None)


def _strip_ignored(text: str, ignore: Iterable[str]) -> str:
    for s in ignore:
        if s:
            text = re.sub(re.escape(s), " ", text, flags=re.IGNORECASE)
    return text


def _resolve_end(begin: int, suffix: int, suffix_digits: int) -> int | None:
    """Resolve a trailing range token to an end year, or None to fall back."""
    if suffix_digits == 4:
        if not (_YEAR_MIN <= suffix <= _YEAR_MAX):
            return None
        return suffix if suffix >= begin else None
    century = begin // 100
    end = century * 100 + suffix
    if end >= begin:
        return end
    # Rollover into the next century only if begin is near the century top —
    # avoids absurd ranges like `1745-08 → 1808` while still catching the
    # natural century-crossing case `1799-02 → 1802`.
    if begin % 100 >= 50:
        return end + 100
    return None


def _single(year: int) -> tuple[str, str]:
    return (f"{year:04d}-01-01", f"{year:04d}-12-31")


def _range(begin: int, end: int) -> tuple[str, str]:
    return (f"{begin:04d}-01-01", f"{end:04d}-12-31")
