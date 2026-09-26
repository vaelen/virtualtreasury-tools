# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

"""Color schemes and match-highlighting helpers shared by every CLI in the
project. Kept here (not under any subpackage) so `vtextract`, `vtindex`, and
`vtbrowse` can all depend on it without circular imports."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field

from rich.text import Text


@dataclass(frozen=True)
class Theme:
    header_style: str
    border_style: str
    match_style: str
    row_styles: tuple[str, ...] = field(default_factory=tuple)
    no_color: bool = False


THEMES: dict[str, Theme] = {
    "dark": Theme(
        header_style="bold cyan", border_style="grey42",
        match_style="bold yellow", row_styles=("", "on grey19"),
    ),
    "light": Theme(
        header_style="bold blue", border_style="grey50",
        match_style="black on yellow", row_styles=("", "on grey85"),
    ),
    "bw": Theme(header_style="bold", border_style="", match_style="reverse"),
    "plain": Theme(header_style="none", border_style="", match_style="", no_color=True),
}

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def highlight_terms(text: str, query: str | None, style: str) -> Text:
    """Return ``text`` as ``rich.Text`` with whole-word case-insensitive
    matches of any query token styled with ``style``. No query or no style
    leaves the text unstyled."""
    out = Text(text)
    if not query or not style:
        return out
    terms = {m.group(0).lower() for m in _WORD_RE.finditer(query)}
    if not terms:
        return out
    for m in _WORD_RE.finditer(text):
        if m.group(0).lower() in terms:
            out.stylize(style, m.start(), m.end())
    return out


def highlight_phrases(out: Text, phrases: list[str], style: str) -> Text:
    """Stylize each whole occurrence of every phrase in ``phrases`` onto the
    already-built ``out`` ``Text`` and return it (mutated in place).

    Unlike :func:`highlight_terms`, a phrase is matched as a contiguous
    sequence of words — "Jno. Smith" highlights only where both words appear
    together, never "Jno." or "Smith" alone. Inter-word whitespace matches
    flexibly (``\\s+``), so a name split across a line break still matches and
    is highlighted as one span. Case-insensitive; each word's outer edge is
    anchored to a word boundary so "Ryan" does not match inside "Ryanair".

    ponytail: whitespace-boundary splits only — a word hyphenated across a
    line ("Smi-\\nth") won't match. Add soft-hyphen handling if archives need it.
    """
    if not style:
        return out
    text = out.plain
    for phrase in phrases:
        tokens = phrase.split()
        if not tokens:
            continue
        pattern = r"(?<!\w)" + r"\s+".join(re.escape(t) for t in tokens) + r"(?!\w)"
        for m in re.finditer(pattern, text, re.IGNORECASE):
            out.stylize(style, m.start(), m.end())
    return out


def add_theme_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared `--dark` / `--light` / `--bw` / `--plain` flags."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dark", dest="theme", action="store_const", const="dark",
                       help="dark-mode color scheme (default)")
    group.add_argument("--light", dest="theme", action="store_const", const="light",
                       help="light-mode color scheme")
    group.add_argument("--bw", dest="theme", action="store_const", const="bw",
                       help="neutral black-and-white scheme (no color fills)")
    group.add_argument("--plain", dest="theme", action="store_const", const="plain",
                       help="disable all colors")
    parser.set_defaults(theme="dark")
