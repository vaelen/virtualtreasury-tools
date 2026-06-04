# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from pydantic import BaseModel

Confidence = Literal["low", "medium", "high"]
CONFIDENCE_LEVELS: tuple[str, ...] = ("low", "medium", "high")

# On-disk sidecar format version. Bump if the sidecar JSON shape changes.
SIDECAR_SCHEMA = 1


def confidence_rank(level: str) -> int:
    return CONFIDENCE_LEVELS.index(level)


def meets_threshold(level: str, threshold: str | None) -> bool:
    if threshold is None:
        return True
    return confidence_rank(level) >= confidence_rank(threshold)


class Alias(BaseModel):
    text: str
    confidence: Confidence = "medium"


class Person(BaseModel):
    canonical: str
    confidence: Confidence = "medium"
    aliases: list[Alias] = []


class NameResponse(BaseModel):
    """The shape the LLM must return for one chunk of text."""

    people: list[Person] = []


@dataclass
class NamesStats:
    extracted: int = 0   # pages a fresh sidecar was written for
    skipped: int = 0     # pages skipped (sidecar already present)
    failed: int = 0      # pages whose extraction failed (no sidecar written)
    people: int = 0      # total Person entries written across all sidecars


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
