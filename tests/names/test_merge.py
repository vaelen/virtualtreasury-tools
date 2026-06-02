# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.names.merge import merge_people
from vtextract.names.models import Person


def test_merge_collapses_same_canonical_keeping_best_confidence():
    a = [Person(canonical="William Young", confidence="low",
                aliases=[{"text": "Wm Young", "confidence": "low"}])]
    b = [Person(canonical="william young", confidence="high",
                aliases=[{"text": "Wm Young", "confidence": "high"},
                         {"text": "Young", "confidence": "medium"}])]
    merged = merge_people([a, b])
    assert len(merged) == 1
    p = merged[0]
    assert p.canonical == "William Young"   # first-seen surface form wins
    assert p.confidence == "high"           # best entry confidence
    alias = {al.text: al.confidence for al in p.aliases}
    assert alias == {"Wm Young": "high", "Young": "medium"}  # best per alias


def test_merge_keeps_distinct_people():
    a = [Person(canonical="John Young")]
    b = [Person(canonical="Thomas Young")]
    merged = merge_people([a, b])
    assert {p.canonical for p in merged} == {"John Young", "Thomas Young"}


def test_merge_empty():
    assert merge_people([]) == []
    assert merge_people([[], []]) == []
