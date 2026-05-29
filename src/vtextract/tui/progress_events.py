# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Typed events parsed from the --json-progress streams emitted by
vtindex build, vtextract search, and vtextract get."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class StartEvent:
    tool: str
    argv: list[str] = field(default_factory=list)


@dataclass
class ProgressUpdate:
    phase: str
    current: int
    total: int | None = None
    counters: dict[str, int] = field(default_factory=dict)


@dataclass
class LogEvent:
    message: str
    level: str = "info"


@dataclass
class DoneEvent:
    elapsed_seconds: float
    counters: dict[str, int] = field(default_factory=dict)


@dataclass
class ErrorEvent:
    message: str
    exit_code: int = 1


ProgressEvent = StartEvent | ProgressUpdate | LogEvent | DoneEvent | ErrorEvent


def parse_event(line: str) -> ProgressEvent:
    data = json.loads(line)
    kind = data.get("event")
    if kind == "start":
        return StartEvent(tool=data["tool"], argv=data.get("argv", []))
    if kind == "progress":
        return ProgressUpdate(phase=data["phase"], current=data["current"],
                              total=data.get("total"),
                              counters=data.get("counters", {}))
    if kind == "log":
        return LogEvent(message=data["message"], level=data.get("level", "info"))
    if kind == "done":
        return DoneEvent(elapsed_seconds=data["elapsed_seconds"],
                         counters=data.get("counters", {}))
    if kind == "error":
        return ErrorEvent(message=data["message"],
                          exit_code=data.get("exit_code", 1))
    raise ValueError(f"unknown event kind: {kind!r}")
