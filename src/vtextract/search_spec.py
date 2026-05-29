# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Build argv for a *single-clause* `vtextract search` invocation. The CLI
itself supports multi-clause searches by repeating field+operand+keyword
groups; this helper is for callers (the vtbrowse Extract dialog, scripts)
that only need a single clause and don't want to re-encode the flag spelling
in two places."""

from __future__ import annotations

from vtextract.models import FIELD_MAP, OPERANDS

# vtbrowse's Extract dialog deliberately omits NONE — it's only meaningful
# when combined with other clauses ("A AND NOT B").
OPERANDS_FOR_SINGLE_CLAUSE: tuple[str, ...] = ("all", "any", "exact")


def build_search_argv(
    *,
    field: str,
    operand: str,
    keywords: str,
    start: str | None,
    end: str | None,
) -> list[str]:
    """Build the argv (minus the program name) for a single-clause search.

    Raises ValueError for unknown field/operand to surface dialog input
    bugs early."""
    if field not in FIELD_MAP:
        raise ValueError(f"unknown field: {field!r}")
    if operand not in OPERANDS_FOR_SINGLE_CLAUSE:
        raise ValueError(f"unknown operand for single-clause search: {operand!r}")

    argv: list[str] = ["search"]
    # The bare `--keyword` flag is the default field; the CLI parses bare
    # words as keywords belonging to the current (default-keyword) clause.
    if field != "keyword":
        argv.append(f"--{field}")
    argv.append(f"--{operand}")
    argv.extend(keywords.split())
    if start:
        argv.extend(["--start", start])
    if end:
        argv.extend(["--end", end])
    return argv
