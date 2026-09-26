# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations


def select_chunk_size(
    text_len: int, *, chunk_size: int, dense_threshold: int, dense_chunk_size: int
) -> int:
    """Pick the chunk size for a page of ``text_len`` characters.

    Long pages — dense name registries and garbled OCR — are what drive the
    model into runaway-output loops. Splitting them into smaller windows keeps
    each generation short, which both lowers the loop probability and bounds the
    wasted output when one does occur. So a page longer than ``dense_threshold``
    uses the smaller ``dense_chunk_size``; everything else keeps the normal
    ``chunk_size`` (and stays a single chunk). ``dense_threshold <= 0`` disables
    the gate.
    """
    if dense_threshold > 0 and dense_chunk_size > 0 and text_len > dense_threshold:
        return dense_chunk_size
    return chunk_size


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int]]:
    """Split text into overlapping windows.

    Returns a list of (window_text, start_offset). Text at or under chunk_size
    yields a single chunk. Consecutive windows overlap by `overlap` characters
    so a name spanning a boundary lands wholly inside at least one window.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    if len(text) <= chunk_size:
        return [(text, 0)]

    chunks: list[tuple[str, int]] = []
    step = chunk_size - overlap
    start = 0
    while start < len(text):
        chunks.append((text[start:start + chunk_size], start))
        if start + chunk_size >= len(text):
            break
        start += step
    return chunks
