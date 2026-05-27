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
