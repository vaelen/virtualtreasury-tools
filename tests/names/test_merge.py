# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.names.merge import merge_people
from vtextract.names.models import Person


def test_merge_collapses_same_canonical_unioning_aliases():
    a = [Person(canonical="William Young", aliases=["Wm Young"])]
    b = [Person(canonical="william young", aliases=["Wm Young", "Young"])]
    merged = merge_people([a, b])
    assert len(merged) == 1
    p = merged[0]
    assert p.canonical == "William Young"          # first-seen surface form wins
    assert p.aliases == ["Wm Young", "Young"]       # unioned, first-seen order


def test_merge_keeps_distinct_people():
    a = [Person(canonical="John Young")]
    b = [Person(canonical="Thomas Young")]
    merged = merge_people([a, b])
    assert {p.canonical for p in merged} == {"John Young", "Thomas Young"}


def test_merge_drops_alias_equal_to_canonical():
    # A model that echoes the canonical as its own surface form must not leave a
    # redundant self-alias in the merged entry.
    a = [Person(canonical="Thomas Young", aliases=["Thomas Young", "Sgt. Young"])]
    merged = merge_people([a])
    assert merged[0].aliases == ["Sgt. Young"]


def test_merge_empty():
    assert merge_people([]) == []
    assert merge_people([[], []]) == []
