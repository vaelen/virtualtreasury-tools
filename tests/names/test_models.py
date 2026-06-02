# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.names.models import (
    Alias,
    NameResponse,
    NamesStats,
    Person,
    confidence_rank,
    meets_threshold,
)


def test_person_defaults_and_aliases():
    p = Person(canonical="William Young", aliases=[{"text": "Wm Young", "confidence": "high"}])
    assert p.confidence == "medium"  # default
    assert p.aliases[0].text == "Wm Young"
    assert isinstance(p.aliases[0], Alias)


def test_name_response_empty_default():
    assert NameResponse().people == []


def test_name_response_parse_full():
    r = NameResponse.model_validate(
        {"people": [{"canonical": "John Young", "confidence": "high",
                     "aliases": [{"text": "J. Young", "confidence": "low"}]}]}
    )
    assert r.people[0].canonical == "John Young"
    assert r.people[0].aliases[0].confidence == "low"


def test_bad_confidence_rejected():
    with pytest.raises(ValueError):
        Person(canonical="X", confidence="certain")


def test_confidence_rank_and_threshold():
    assert confidence_rank("low") < confidence_rank("high")
    assert meets_threshold("high", "medium") is True
    assert meets_threshold("low", "medium") is False
    assert meets_threshold("low", None) is True


def test_names_stats_defaults():
    s = NamesStats()
    assert (s.extracted, s.skipped, s.failed, s.people) == (0, 0, 0, 0)
