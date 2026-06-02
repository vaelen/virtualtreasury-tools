# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.names.chunking import chunk_text


def test_short_text_single_chunk():
    assert chunk_text("hello", 64000, 512) == [("hello", 0)]


def test_long_text_overlapping_windows():
    text = "abcdefghij"  # len 10
    chunks = chunk_text(text, 4, 1)
    # step = 3; the final window ("ghij", 6) already covers the tail, so the
    # chunker breaks rather than emitting a redundant ("j", 9) window that is
    # fully contained in the previous window's overlap.
    assert chunks == [("abcd", 0), ("defg", 3), ("ghij", 6)]


def test_invalid_args():
    with pytest.raises(ValueError):
        chunk_text("x", 0, 0)
    with pytest.raises(ValueError):
        chunk_text("x", 4, 4)
