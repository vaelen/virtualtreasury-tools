# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.names.chunking import chunk_text, select_chunk_size


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


def test_select_chunk_size_uses_normal_size_at_or_below_threshold():
    # A page no larger than the dense threshold keeps the normal (big) chunk
    # size, so it stays a single chunk.
    assert select_chunk_size(5000, chunk_size=64000,
                             dense_threshold=5000, dense_chunk_size=3000) == 64000


def test_select_chunk_size_uses_dense_size_above_threshold():
    # A page larger than the threshold is chunked at the small dense size so each
    # generation is short (bounding runaway-output loops on dense pages).
    assert select_chunk_size(5001, chunk_size=64000,
                             dense_threshold=5000, dense_chunk_size=3000) == 3000


def test_select_chunk_size_threshold_zero_disables_gate():
    # threshold 0 disables adaptive chunking entirely -> always the normal size.
    assert select_chunk_size(1_000_000, chunk_size=64000,
                             dense_threshold=0, dense_chunk_size=3000) == 64000
