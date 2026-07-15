# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""_build_body highlights the searched person's on-page surface form, even
when it differs from the typed name (the whole point of this feature)."""

import json

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle
from vtextract.tui.screens.transcription import TranscriptionScreen


def _screen(archive, *, query=None, person=None):
    return TranscriptionScreen(
        index=None, reader=ArchiveReader(archive), bundle=Bundle(),
        root_id="0007", page_key="cb_001.jpg", query=query, person=person)


def _styled_slices(text_widget):
    """The substrings of a rendered Static's Text that carry a style span."""
    body = getattr(text_widget, "_Static__content")  # the rich.Text handed to Static()
    return {body.plain[s.start:s.end] for s in body.spans}


def _build_archive(tmp_path, text):
    page_dir = tmp_path / "archive" / "pages" / "0007"
    page_dir.mkdir(parents=True)
    (page_dir / "cb_001.jpg.txt").write_text(text)
    (page_dir / "cb_001.jpg.names.json").write_text(json.dumps(
        {"people": [["John Smith", "Jno. Smith"], ["Patrick Ryan"]]}))
    return tmp_path / "archive"


def test_person_search_highlights_exact_on_page_variant(tmp_path):
    archive = _build_archive(tmp_path, "Paid to Jno. Smith and to Patrick Ryan.\n")
    # Person-only search: free-text query is empty, person is "John Smith".
    styled = _styled_slices(_screen(archive, query="", person="John Smith")._build_body())
    # The exact on-page form is highlighted whole — not "Jno." or "Smith" alone.
    assert styled == {"Jno. Smith"}


def test_person_search_highlights_name_split_across_lines(tmp_path):
    archive = _build_archive(tmp_path, "Paid to John\nSmith for the works.\n")
    styled = _styled_slices(_screen(archive, query="", person="John Smith")._build_body())
    assert styled == {"John\nSmith"}


def test_no_person_leaves_variant_unhighlighted(tmp_path):
    archive = _build_archive(tmp_path, "Paid to Jno. Smith and to Patrick Ryan.\n")
    styled = _styled_slices(_screen(archive, query="", person=None)._build_body())
    assert styled == set()
