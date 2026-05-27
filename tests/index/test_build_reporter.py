# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from io import StringIO

from rich.console import Console

from vtextract.progress import BuildReporter


def _build_reporter():
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    return BuildReporter(console=console, enabled=False), buf


def test_build_reporter_emits_neutral_lines():
    reporter, buf = _build_reporter()
    with reporter:
        reporter.start(3)
        reporter.advance()
        reporter.advance()
        reporter.advance()
    reporter.finish(added=1, updated=1, removed=0, unchanged=1, skipped=0)

    out = buf.getvalue()
    assert "Indexing 3 files." in out
    assert "indexed: 1 added, 1 updated, 0 removed, 1 unchanged, 0 skipped" in out
