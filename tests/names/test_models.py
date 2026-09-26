# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import pytest
from pydantic import ValidationError

from vtextract.names.models import (
    NameResponse,
    NamesStats,
    Person,
    Usage,
    people_and_usage,
    person_to_entry,
    sum_usage,
)


def test_person_has_canonical_and_string_aliases():
    p = Person(canonical="William Young", aliases=["Wm Young", "Young"])
    assert p.canonical == "William Young"
    assert p.aliases == ["Wm Young", "Young"]


def test_person_aliases_default_empty():
    assert Person(canonical="B. McHugh").aliases == []


def test_name_response_empty_default():
    assert NameResponse().people == []


def test_name_response_parses_list_of_lists():
    r = NameResponse.model_validate(
        {"people": [["John Young", "J. Young"], ["B. McHugh"]]}
    )
    assert r.people[0].canonical == "John Young"
    assert r.people[0].aliases == ["J. Young"]
    assert r.people[1].canonical == "B. McHugh"
    assert r.people[1].aliases == []


def test_name_response_rejects_empty_entry():
    with pytest.raises(ValidationError):
        NameResponse.model_validate({"people": [[]]})


def test_name_response_rejects_non_list_entry():
    with pytest.raises(ValidationError):
        NameResponse.model_validate({"people": [{"canonical": "X"}]})


def test_name_response_rejects_non_string_element():
    with pytest.raises(ValidationError):
        NameResponse.model_validate({"people": [["X", 7]]})


def test_person_to_entry_is_canonical_then_aliases():
    p = Person(canonical="William Young", aliases=["Wm Young"])
    assert person_to_entry(p) == ["William Young", "Wm Young"]
    assert person_to_entry(Person(canonical="B. McHugh")) == ["B. McHugh"]


def test_sidecar_schema_is_2():
    from vtextract.names.models import SIDECAR_SCHEMA
    assert SIDECAR_SCHEMA == 2


def test_error_sidecar_schema_constant_present():
    from vtextract.names.models import ERROR_SIDECAR_SCHEMA
    assert ERROR_SIDECAR_SCHEMA == 1


def test_names_stats_defaults():
    s = NamesStats()
    assert (s.extracted, s.skipped, s.failed, s.people) == (0, 0, 0, 0)


def test_names_stats_has_failure_buckets():
    s = NamesStats()
    assert s.parked == 0
    assert s.failed_persistent == 0


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
    assert Usage.from_dict({"in": 5, "out": 1}) == Usage(input=5, output=1, cached=0)


def test_sum_usage_ignores_none_and_returns_none_when_all_unknown():
    assert sum_usage([None, None]) is None
    assert sum_usage([]) is None
    assert sum_usage([Usage(input=1, output=2), None, Usage(input=3, output=4)]) == \
        Usage(input=4, output=6, cached=0)


def test_people_and_usage_normalizes_both_seam_shapes():
    people = [Person(canonical="A")]
    assert people_and_usage(people) == (people, None)
    u = Usage(input=1, output=1)
    assert people_and_usage((people, u)) == (people, u)
