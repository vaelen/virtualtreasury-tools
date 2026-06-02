# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
