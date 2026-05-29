# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Enforces the architectural boundary documented in
docs/superpowers/specs/2026-05-29-vtbrowse-tui-design.md §Architectural
boundaries: vtbrowse never imports the index DB / query / builder / fetcher /
HTTP client. If you need data from those modules, go through index_client,
extract_client, or archive_reader."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN = (
    "vtextract.index.db",
    "vtextract.index.query",
    "vtextract.index.builder",
    "vtextract.fetcher",
    "vtextract.client",
)

TUI_ROOT = Path(__file__).resolve().parents[1] / "src" / "vtextract" / "tui"


def test_tui_does_not_import_forbidden_modules():
    pattern = re.compile(
        r"(?:from|import)\s+(" + "|".join(re.escape(m) for m in FORBIDDEN) + r")\b"
    )
    offenders: list[str] = []
    for py in TUI_ROOT.rglob("*.py"):
        text = py.read_text()
        for match in pattern.finditer(text):
            offenders.append(f"{py.relative_to(TUI_ROOT.parents[2])}: {match.group(0)}")
    assert not offenders, (
        "vtbrowse modules must go through index_client / extract_client / "
        "archive_reader instead of importing these directly:\n  "
        + "\n  ".join(offenders)
    )
