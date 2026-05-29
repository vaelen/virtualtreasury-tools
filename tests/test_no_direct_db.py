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

# Names that, when imported as a submodule of ``vtextract.index``, indicate
# someone reached past index_client. Distinct from the full-dotted-path
# FORBIDDEN set because of `from vtextract.index import db, query`.
FORBIDDEN_INDEX_SUBMODULES = ("db", "query", "builder")

# Top-level forbidden modules that may also be reached via
# ``from vtextract import client, fetcher``.
FORBIDDEN_VT_SUBMODULES = ("fetcher", "client")

TUI_ROOT = Path(__file__).resolve().parents[1] / "src" / "vtextract" / "tui"


def test_tui_does_not_import_forbidden_modules():
    full_pattern = re.compile(
        r"(?:from|import)\s+(" + "|".join(re.escape(m) for m in FORBIDDEN) + r")\b"
    )
    # `from vtextract.index import db, query` style — the submodule name lives
    # in the import target list, not the path. Match the whole tail and then
    # split it ourselves so we catch any of the forbidden names anywhere in
    # the list (handles trailing commas, parentheses, aliases, etc.).
    index_pattern = re.compile(
        r"from\s+vtextract\.index\s+import\s+([^\n#]+)"
    )
    vt_pattern = re.compile(
        r"from\s+vtextract\s+import\s+([^\n#]+)"
    )
    offenders: list[str] = []
    for py in TUI_ROOT.rglob("*.py"):
        text = py.read_text()
        for match in full_pattern.finditer(text):
            offenders.append(
                f"{py.relative_to(TUI_ROOT.parents[2])}: {match.group(0)}"
            )
        for match in index_pattern.finditer(text):
            tail = match.group(1)
            # Strip parens and split into bare names (drop "as <alias>").
            names = {
                n.strip().split()[0]
                for n in tail.replace("(", "").replace(")", "").split(",")
                if n.strip()
            }
            for forbidden in FORBIDDEN_INDEX_SUBMODULES:
                if forbidden in names:
                    offenders.append(
                        f"{py.relative_to(TUI_ROOT.parents[2])}: "
                        f"from vtextract.index import {forbidden}"
                    )
        for match in vt_pattern.finditer(text):
            tail = match.group(1)
            names = {
                n.strip().split()[0]
                for n in tail.replace("(", "").replace(")", "").split(",")
                if n.strip()
            }
            for forbidden in FORBIDDEN_VT_SUBMODULES:
                if forbidden in names:
                    offenders.append(
                        f"{py.relative_to(TUI_ROOT.parents[2])}: "
                        f"from vtextract import {forbidden}"
                    )
    assert not offenders, (
        "vtbrowse modules must go through index_client / extract_client / "
        "archive_reader instead of importing these directly:\n  "
        + "\n  ".join(offenders)
    )
