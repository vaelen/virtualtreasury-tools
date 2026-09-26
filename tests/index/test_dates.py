# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import pytest

from vtextract.index.dates import parse_year_range


@pytest.mark.parametrize(
    "text,expected",
    [
        # single 4-digit year
        ("PRONI Deeds Volume 25: 1689", ("1689-01-01", "1689-12-31")),
        # 4-digit to 4-digit range
        ("The Drennan-McTier letters, Vol. 2: 1794-1801", ("1794-01-01", "1801-12-31")),
        # 4-digit to 2-digit range (century rollover within the same century)
        ("abstracts of wills, volume 1: 1708-45", ("1708-01-01", "1745-12-31")),
        # 4-digit to 2-digit range that crosses a century boundary
        ("Records 1799-02", ("1799-01-01", "1802-12-31")),
        # unicode en-dash separator
        ("Letters 1708–1745", ("1708-01-01", "1745-12-31")),
        # unicode em-dash separator
        ("Letters 1708—1745", ("1708-01-01", "1745-12-31")),
        # first qualifying match wins; earlier "Volume 1" is not a year
        ("Registry of Deeds, Dublin: abstracts of wills, volume 1: 1708-45",
         ("1708-01-01", "1745-12-31")),
        # no match: just text
        ("Untitled record", (None, None)),
        # no match: empty string
        ("", (None, None)),
        # no match: number out of band (year too low / too high)
        ("Book 1234 of the catalogue", (None, None)),
        ("Future records 2150", (None, None)),
    ],
)
def test_parse_year_range_basic(text, expected):
    assert parse_year_range(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # catalogue-style: year is part of a `/`-separated path
        "IMC 1954/RoD/1",
        "RoD/1954",
        "IMC 1954/RoD/1/86",
        # alphanumeric token: year glued to letters is part of a code
        "MS1954",
        "1954MS",
    ],
)
def test_parse_year_range_rejects_catalogue_patterns(text):
    """Years inside catalogue-like tokens (slashes, letter-glued) are rejected."""
    assert parse_year_range(text) == (None, None)


def test_parse_year_range_ignore_strips_reference_code():
    """A reference code passed in `ignore` is stripped from the text first."""
    text = "IMC 1954/RoD/1: misc papers"
    assert parse_year_range(text, ignore=["IMC 1954/RoD/1"]) == (None, None)


def test_parse_year_range_ignore_preserves_real_year_after_ref_code():
    """After stripping the ref code, a genuine trailing year still parses."""
    text = "IMC 1954/RoD/1: abstracts 1708-45"
    assert parse_year_range(text, ignore=["IMC 1954/RoD/1"]) == ("1708-01-01", "1745-12-31")


def test_parse_year_range_ignore_case_insensitive():
    """`ignore` matching is case-insensitive (ref codes are upper-case but
    user text might not be)."""
    text = "imc 1954/rod/1: nothing else"
    assert parse_year_range(text, ignore=["IMC 1954/RoD/1"]) == (None, None)


def test_parse_year_range_rejects_inverted_range():
    """A range whose end precedes its begin (even after rollover) is rejected."""
    # 1745-08 -> rollover would give 1708, which is < 1745 → reject the range,
    # but the lone 1745 should still match as a single year.
    assert parse_year_range("Records 1745-08") == ("1745-01-01", "1745-12-31")
