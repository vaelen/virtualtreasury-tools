# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pydantic import BaseModel, model_validator

# On-disk sidecar format version. Bump if the sidecar JSON shape changes.
# v2: people are compact ``[canonical, *surface_forms]`` arrays (no confidence).
SIDECAR_SCHEMA = 2

# On-disk error-sidecar format version. Bump if the error JSON shape changes.
ERROR_SIDECAR_SCHEMA = 1


class Person(BaseModel):
    """One person: a canonical name plus the verbatim surface forms seen.

    ``canonical`` is the normalized/expanded identity (may not appear verbatim,
    e.g. "William Young" from "Wm Young"); ``aliases`` are the literal surface
    strings that appeared in the text (e.g. "Wm Young", "Sgt. Young").
    """

    canonical: str
    aliases: list[str] = []


def _entry_to_person(entry: object) -> dict:
    """Coerce a wire entry ``[canonical, *aliases]`` into Person kwargs.

    Raises ValueError on anything else so the model's malformed output surfaces
    as a ValidationError and hits the JSON-repair retry path.
    """
    if not isinstance(entry, list) or not entry:
        raise ValueError("each person must be a non-empty [canonical, *aliases] list")
    if not all(isinstance(x, str) for x in entry):
        raise ValueError("person entries must contain only strings")
    return {"canonical": entry[0], "aliases": list(entry[1:])}


class NameResponse(BaseModel):
    """The shape the LLM must return for one chunk of text.

    Wire form is ``{"people": [[canonical, *surface_forms], ...]}``; each inner
    array is coerced into a :class:`Person` before validation.
    """

    people: list[Person] = []

    @model_validator(mode="before")
    @classmethod
    def _coerce_entries(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("people"), list):
            return {**data, "people": [_entry_to_person(e) for e in data["people"]]}
        return data


def person_to_entry(person: Person) -> list[str]:
    """Serialize a Person to the compact wire form ``[canonical, *aliases]``."""
    return [person.canonical, *person.aliases]


@dataclass
class NamesStats:
    extracted: int = 0          # pages a fresh sidecar was written for
    skipped: int = 0            # pages skipped (success sidecar already present)
    parked: int = 0             # pages skipped (persistent-error sidecar present)
    failed: int = 0             # transient failures this run (no sidecar written)
    failed_persistent: int = 0  # persistent failures this run (error sidecar written)
    people: int = 0             # total Person entries written across all sidecars


@dataclass(frozen=True)
class Usage:
    """LLM token usage for one extraction, normalized across providers.

    ``input``/``output`` are the provider's prompt/completion token counts;
    ``cached`` is how many of the *input* tokens were served from a prompt cache
    (a subset of ``input`` — cache *hits*, i.e. litellm's
    ``prompt_tokens_details.cached_tokens`` / Anthropic ``cache_read``). Note
    that Anthropic cache *creation* (write) tokens are counted in ``input`` but
    not in ``cached``, so ``cached`` reflects cheap re-reads, not writes.
    """

    input: int = 0
    output: int = 0
    cached: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input + other.input,
                     self.output + other.output,
                     self.cached + other.cached)

    def to_dict(self) -> dict:
        """Sidecar form, with the agreed short keys."""
        return {"in": self.input, "out": self.output,
                "total": self.total, "cached": self.cached}

    @classmethod
    def from_dict(cls, d: dict) -> "Usage":
        return cls(input=int(d.get("in", 0)),
                   output=int(d.get("out", 0)),
                   cached=int(d.get("cached", 0)))


def sum_usage(items: Iterable[Usage | None]) -> Usage | None:
    """Sum usages, skipping unknown (None) entries.

    Returns None when every entry is None (no real token data) so callers can
    distinguish "nothing recorded" from a genuine zero-token result.
    """
    total: Usage | None = None
    for u in items:
        if u is None:
            continue
        total = u if total is None else total + u
    return total


def people_and_usage(result: object) -> tuple[list["Person"], Usage | None]:
    """Normalize a ``FindFn`` result into (people, usage).

    The production ``find_people`` returns ``(people, usage)``; test fakes and
    older seams return a bare ``list[Person]`` (usage unknown -> None). This is
    the single place both shapes are reconciled.
    """
    if (isinstance(result, tuple) and len(result) == 2
            and isinstance(result[0], list)):
        return result[0], result[1]
    return result, None  # type: ignore[return-value]
