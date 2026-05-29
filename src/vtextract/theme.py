# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

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
