# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from vtextract.names.models import Alias, Person, confidence_rank


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def merge_people(groups: list[list[Person]]) -> list[Person]:
    """Merge per-chunk people lists into one deduped list.

    People are the same when their canonical names match after whitespace/case
    normalization. The first-seen canonical surface form is kept; the entry
    confidence becomes the best (highest) seen; aliases are unioned by
    normalized text, each keeping its highest confidence. First-seen order is
    preserved for both people and aliases.
    """
    by_key: dict[str, Person] = {}
    alias_order: dict[str, list[str]] = {}
    alias_best: dict[str, dict[str, Alias]] = {}
    order: list[str] = []

    for group in groups:
        for person in group:
            key = _norm(person.canonical)
            if key not in by_key:
                by_key[key] = Person(canonical=person.canonical, confidence=person.confidence)
                alias_order[key] = []
                alias_best[key] = {}
                order.append(key)
            else:
                existing = by_key[key]
                if confidence_rank(person.confidence) > confidence_rank(existing.confidence):
                    existing.confidence = person.confidence
            for al in person.aliases:
                ak = _norm(al.text)
                cur = alias_best[key].get(ak)
                if cur is None:
                    alias_best[key][ak] = Alias(text=al.text, confidence=al.confidence)
                    alias_order[key].append(ak)
                elif confidence_rank(al.confidence) > confidence_rank(cur.confidence):
                    cur.confidence = al.confidence

    result: list[Person] = []
    for key in order:
        person = by_key[key]
        person.aliases = [alias_best[key][ak] for ak in alias_order[key]]
        result.append(person)
    return result
