# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.names.models import (
    Alias,
    NameResponse,
    NamesStats,
    Person,
    Usage,
    confidence_rank,
    meets_threshold,
    people_and_usage,
    sum_usage,
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


def test_usage_total_is_in_plus_out():
    u = Usage(input=1144, output=304, cached=512)
    assert u.total == 1448


def test_usage_addition_sums_each_field():
    a = Usage(input=10, output=2, cached=3)
    b = Usage(input=5, output=1, cached=0)
    c = a + b
    assert (c.input, c.output, c.cached, c.total) == (15, 3, 3, 18)


def test_usage_to_dict_uses_in_out_total_cached_keys():
    u = Usage(input=100, output=20, cached=64)
    assert u.to_dict() == {"in": 100, "out": 20, "total": 120, "cached": 64}


def test_usage_from_dict_roundtrips():
    u = Usage(input=100, output=20, cached=64)
    assert Usage.from_dict(u.to_dict()) == u
    # tolerates a missing cached key (older partial data)
    assert Usage.from_dict({"in": 5, "out": 1}) == Usage(input=5, output=1, cached=0)


def test_sum_usage_ignores_none_and_returns_none_when_all_unknown():
    assert sum_usage([None, None]) is None
    assert sum_usage([]) is None
    assert sum_usage([Usage(input=1, output=2), None, Usage(input=3, output=4)]) == \
        Usage(input=4, output=6, cached=0)


def test_people_and_usage_normalizes_both_seam_shapes():
    people = [Person(canonical="A")]
    # a fake find that returns a bare list -> usage unknown
    assert people_and_usage(people) == (people, None)
    # the production shape (people, usage)
    u = Usage(input=1, output=1)
    assert people_and_usage((people, u)) == (people, u)
