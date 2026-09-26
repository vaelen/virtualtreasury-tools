# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import json

import pytest

from vtextract.tui.progress_events import (
    DoneEvent, ErrorEvent, LogEvent, ProgressUpdate, StartEvent,
    parse_event,
)


def test_parse_start():
    e = parse_event(json.dumps({"event": "start", "tool": "vtindex build",
                                "argv": ["--rebuild"]}))
    assert isinstance(e, StartEvent)
    assert e.tool == "vtindex build" and e.argv == ["--rebuild"]


def test_parse_progress():
    e = parse_event(json.dumps({"event": "progress", "phase": "indexing",
                                "current": 50, "total": 100,
                                "counters": {"added": 10}}))
    assert isinstance(e, ProgressUpdate)
    assert e.phase == "indexing" and e.current == 50 and e.total == 100
    assert e.counters == {"added": 10}


def test_parse_log_defaults_level_to_info():
    e = parse_event(json.dumps({"event": "log", "message": "hi"}))
    assert isinstance(e, LogEvent)
    assert e.level == "info" and e.message == "hi"


def test_parse_done():
    e = parse_event(json.dumps({"event": "done", "elapsed_seconds": 1.5,
                                "counters": {"added": 1}}))
    assert isinstance(e, DoneEvent)
    assert e.elapsed_seconds == 1.5 and e.counters == {"added": 1}


def test_parse_error():
    e = parse_event(json.dumps({"event": "error", "message": "boom",
                                "exit_code": 2}))
    assert isinstance(e, ErrorEvent)
    assert e.message == "boom" and e.exit_code == 2


def test_unknown_event_raises():
    with pytest.raises(ValueError):
        parse_event(json.dumps({"event": "weird"}))
