# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from vtextract.names.models import Person


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def merge_people(groups: list[list[Person]]) -> list[Person]:
    """Merge per-chunk people lists into one deduped list.

    People are the same when their canonical names match after whitespace/case
    normalization. The first-seen canonical surface form is kept; aliases are
    unioned by normalized text, dropping any that merely re-state the canonical.
    First-seen order is preserved for both people and aliases.
    """
    by_key: dict[str, Person] = {}
    alias_order: dict[str, list[str]] = {}
    alias_first: dict[str, dict[str, str]] = {}
    order: list[str] = []

    for group in groups:
        for person in group:
            key = _norm(person.canonical)
            if key not in by_key:
                by_key[key] = Person(canonical=person.canonical)
                alias_order[key] = []
                alias_first[key] = {}
                order.append(key)
            for alias in person.aliases:
                ak = _norm(alias)
                if ak == key:  # a surface form identical to the canonical
                    continue
                if ak not in alias_first[key]:
                    alias_first[key][ak] = alias
                    alias_order[key].append(ak)

    result: list[Person] = []
    for key in order:
        person = by_key[key]
        person.aliases = [alias_first[key][ak] for ak in alias_order[key]]
        result.append(person)
    return result
