# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from io import StringIO

from rich.console import Console

from vtextract.progress import Reporter


def _reporter():
    """A Reporter writing plain text to a buffer, as if piped (no live bars)."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    return Reporter(console=console, enabled=False), buf


def test_reporter_emits_plain_status_lines():
    reporter, buf = _reporter()
    with reporter:
        reporter.set_total(5)
        reporter.start_item(123)
        reporter.item_pages(2)
        reporter.page_done()
        reporter.page_done()
        reporter.item_done(123)
        reporter.skip(456)
        reporter.fail(789, ValueError("boom"))
    reporter.finish(1, 1)

    out = buf.getvalue()
    assert "Found 5 matches." in out
    assert "fetching 123..." in out
    assert "done 123" in out
    assert "skipping 456, already archived" in out
    assert "FAILED 789" in out
    assert "finished: 1 archived, 1 failed" in out


def test_set_total_noun_is_configurable():
    reporter, buf = _reporter()
    reporter.set_total(3, noun="resources")
    assert "Found 3 resources." in buf.getvalue()


def test_verify_summary_prints_counts_and_flagged_paths():
    import io
    from rich.console import Console
    from vtextract.progress import Reporter

    buf = io.StringIO()
    reporter = Reporter(console=Console(file=buf, width=200), enabled=False)
    reporter.verify_summary(
        {"ok": 3, "mismatch": 1, "missing": 2, "unverified": 1},
        ["pages/v/a.jpg", "pages/v/b.jpg"],
    )
    out = buf.getvalue()
    assert "3 ok" in out
    assert "1 re-downloaded" in out
    assert "2 downloaded" in out
    assert "1 unverified" in out
    assert "pages/v/a.jpg" in out and "pages/v/b.jpg" in out


import io
import json

from vtextract.progress import JsonBuildReporter, JsonFetchReporter


def _events(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_json_build_reporter_emits_start_progress_finish():
    out = io.StringIO()
    with JsonBuildReporter(stream=out) as r:
        r.start(total=10)
        r.advance_overall(7)
        r.finish(added=5, updated=2, removed=0, unchanged=3, skipped=0)
    events = _events(out)
    assert events[0]["event"] == "start"
    assert events[0]["tool"] == "vtindex build"
    assert any(e["event"] == "progress" and e["current"] == 7 for e in events)
    done = [e for e in events if e["event"] == "done"][0]
    assert done["counters"] == {"added": 5, "updated": 2, "removed": 0,
                                "unchanged": 3, "skipped": 0}


def test_json_fetch_reporter_emits_per_item_events():
    out = io.StringIO()
    with JsonFetchReporter(stream=out) as r:
        r.set_total(2)
        r.start_item("abc")
        r.item_pages(3)
        r.page_done()
        r.page_done()
        r.page_done()
        r.item_done(123)
        r.finish(completed=1, failed=0)
    events = _events(out)
    kinds = [e["event"] for e in events]
    assert "start" in kinds and "done" in kinds
    assert any(e["event"] == "log" and "abc" in e["message"] for e in events)
    # item_done must have emitted a progress event with current >= 1
    assert any(
        e["event"] == "progress" and e.get("phase") == "fetching" and e.get("current", 0) >= 1
        for e in events
    )


def test_json_reporter_emit_error_terminates_with_error_event():
    out = io.StringIO()
    r = JsonBuildReporter(stream=out)
    r.emit_error("boom", exit_code=2)
    err = [e for e in _events(out) if e["event"] == "error"][0]
    assert err == {"event": "error", "message": "boom", "exit_code": 2}
