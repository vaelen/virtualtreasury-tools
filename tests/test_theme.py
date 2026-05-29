# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.theme import THEMES, Theme, highlight_terms


def test_themes_dict_has_expected_keys():
    assert set(THEMES) == {"dark", "light", "bw", "plain"}
    assert all(isinstance(t, Theme) for t in THEMES.values())


def test_plain_theme_disables_color():
    assert THEMES["plain"].no_color is True


def test_highlight_terms_marks_only_matching_words():
    text = highlight_terms("Pirate sightings off Dublin", "pirate dublin", "bold yellow")
    spans = [(s.start, s.end, str(s.style)) for s in text.spans]
    assert (0, 6, "bold yellow") in spans
    assert (21, 27, "bold yellow") in spans


def test_highlight_terms_returns_plain_text_when_query_or_style_missing():
    assert highlight_terms("Pirate", None, "bold").spans == []
    assert highlight_terms("Pirate", "pirate", "").spans == []
