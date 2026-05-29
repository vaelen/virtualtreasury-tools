# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.search_spec import OPERANDS_FOR_SINGLE_CLAUSE, build_search_argv


def test_default_keyword_field_uses_bare_keyword_flag():
    argv = build_search_argv(field="keyword", operand="all",
                             keywords="pirate Dublin", start=None, end=None)
    assert argv == ["search", "--all", "pirate", "Dublin"]


def test_title_any_with_dates():
    argv = build_search_argv(field="title", operand="any",
                             keywords="pirate Dublin",
                             start="1640-01-01", end="1660-12-31")
    assert argv == ["search", "--title", "--any", "pirate", "Dublin",
                    "--start", "1640-01-01", "--end", "1660-12-31"]


def test_transcription_exact_no_dates():
    argv = build_search_argv(field="transcription", operand="exact",
                             keywords="Lord Lieutenant", start=None, end=None)
    assert argv == ["search", "--transcription", "--exact",
                    "Lord", "Lieutenant"]


def test_single_clause_operands_excludes_none():
    assert set(OPERANDS_FOR_SINGLE_CLAUSE) == {"all", "any", "exact"}


def test_unknown_field_raises():
    with pytest.raises(ValueError):
        build_search_argv(field="bogus", operand="all", keywords="x",
                          start=None, end=None)


def test_unknown_operand_raises():
    with pytest.raises(ValueError):
        build_search_argv(field="title", operand="none", keywords="x",
                          start=None, end=None)
