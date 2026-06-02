# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations


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
