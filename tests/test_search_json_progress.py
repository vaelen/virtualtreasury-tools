# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""End-to-end JSONL shape checks for vtextract --json-progress.

Drives vtextract.cli.run() in-process with a stubbed MockTransport (the same
seam test_cli.py uses) and parses stdout as JSON Lines, asserting:
- first event is ``start`` with ``tool == "vtextract fetch"``,
- last event is ``done`` with a numeric ``elapsed_seconds`` and a ``counters`` dict,
- every line in between is a valid JSON object with an ``event`` key.

Covers ``search``, ``get``, and ``refresh`` so all three subparsers stay wired.
"""

import json
import shutil
from pathlib import Path

import httpx
import pytest

from vtextract import cli
from vtextract.config import write_config


EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def _write_config(tmp_path, token="x", delay=0, max_retries=3):
    path = tmp_path / "vt.toml"
    write_config(
        path,
        {"extract": {"auth": {"token": token},
                     "http": {"delay": delay, "max_retries": max_retries}}},
    )
    return path


def _item_handler(request, search_response=None):
    """Mirror of test_cli._item_handler; returns committed fixture bytes."""
    path = request.url.path
    if path == "/IR_REST_V2/webapi/doc_search":
        return httpx.Response(200, json=search_response or {})
    if path == "/rest/isadg-identity-statements/" and request.url.params.get("isadgReferenceCode"):
        return httpx.Response(
            200,
            content=(EXAMPLES / "item" / "isadg-identity-statements" / "response.json").read_bytes(),
        )
    if path == "/rest/isadg-identity-statements/474234":
        return httpx.Response(
            200,
            content=(EXAMPLES / "item" / "isadg-identity-statements" / "response.json").read_bytes(),
        )
    if path == "/iiif/v1/474234/manifest":
        return httpx.Response(
            200,
            content=(EXAMPLES / "item" / "manifest" / "response.json").read_bytes(),
        )
    if path == "/iiif/v1/208925/list/197350":
        return httpx.Response(
            200,
            content=(EXAMPLES / "item" / "list" / "response.json").read_bytes(),
        )
    if path.startswith("/loris/"):
        return httpx.Response(
            200,
            content=(EXAMPLES / "item" / "loris" / "response.jpg").read_bytes(),
        )
    return httpx.Response(404, text=path)


def _parse_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _assert_well_formed(events: list[dict]) -> None:
    assert events, "expected at least one JSON event on stdout"
    assert events[0]["event"] == "start"
    assert events[0]["tool"] == "vtextract fetch"
    assert events[-1]["event"] == "done"
    done = events[-1]
    assert "elapsed_seconds" in done
    assert isinstance(done.get("counters"), dict)
    # Every event must be a dict with an "event" key.
    for e in events:
        assert isinstance(e, dict)
        assert isinstance(e.get("event"), str)


def test_search_json_progress_emits_jsonl_shape(tmp_path, monkeypatch, capsys):
    config = _write_config(tmp_path)
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}
        ],
    }
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _item_handler(r, search_response)),
    )

    exit_code = cli.run(
        ["search", "houston", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config), "--json-progress"],
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    events = _parse_jsonl(captured.out)
    _assert_well_formed(events)
    # The fetch loop should report a done counter for the one completed resource.
    done = events[-1]
    assert done["counters"].get("completed") == 1
    assert done["counters"].get("failed") == 0


def test_get_json_progress_emits_jsonl_shape(tmp_path, monkeypatch, capsys):
    config = _write_config(tmp_path)
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _item_handler(r)),
    )

    exit_code = cli.run(
        ["get", "474234", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config), "--json-progress"],
    )
    assert exit_code == 0
    events = _parse_jsonl(capsys.readouterr().out)
    _assert_well_formed(events)
    assert events[-1]["counters"].get("completed") == 1


def test_refresh_json_progress_emits_jsonl_shape(tmp_path, monkeypatch, capsys):
    config = _write_config(tmp_path)
    # Seed one item so refresh has something to enumerate.
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _item_handler(r)),
    )
    assert cli.run(
        ["get", "474234", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config)],
    ) == 0
    capsys.readouterr()  # discard the get output

    exit_code = cli.run(
        ["refresh", "--yes", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config), "--json-progress"],
    )
    assert exit_code == 0
    events = _parse_jsonl(capsys.readouterr().out)
    _assert_well_formed(events)
