# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.theme import THEMES, Theme, highlight_phrases, highlight_terms
from rich.text import Text


def _styled(text: Text) -> set[str]:
    return {text.plain[s.start:s.end] for s in text.spans}


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


def test_highlight_phrases_matches_whole_phrase_not_single_words():
    out = highlight_phrases(Text("Paid to Jno. Smith and to John Doe."),
                            ["Jno. Smith"], "bold yellow")
    # The full form is highlighted as one span; a shared word alone is not.
    assert _styled(out) == {"Jno. Smith"}


def test_highlight_phrases_spans_a_line_break():
    # "John" ends one line, "Smith" starts the next.
    out = highlight_phrases(Text("witnessed by John\nSmith of Cork"),
                            ["John Smith"], "bold yellow")
    assert _styled(out) == {"John\nSmith"}


def test_highlight_phrases_respects_word_boundaries():
    out = highlight_phrases(Text("the Ryanair desk"), ["Ryan"], "bold yellow")
    assert out.spans == []


def test_highlight_phrases_no_style_leaves_text_unstyled():
    assert highlight_phrases(Text("Jno. Smith"), ["Jno. Smith"], "").spans == []
