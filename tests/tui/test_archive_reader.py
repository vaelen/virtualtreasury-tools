# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import json

import pytest

from vtextract.tui.archive_reader import ArchiveReader


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "archive"
    page_dir = root / "pages" / "0007"
    page_dir.mkdir(parents=True)
    (page_dir / "cb_001.jpg.txt").write_text("transcription body\n")
    (page_dir / "cb_001.jpg.json").write_text(json.dumps({"resources": []}))
    (page_dir / "volume.json").write_text(json.dumps(
        {"root_id": "0007", "title": "Council Book", "reference_code": "CB/1640"}))
    return root


def test_read_transcription(archive):
    r = ArchiveReader(archive)
    assert r.read_transcription("0007", "cb_001.jpg") == "transcription body\n"


def test_read_transcription_missing_returns_none(archive):
    r = ArchiveReader(archive)
    assert r.read_transcription("0007", "missing.jpg") is None


def test_read_volume_meta(archive):
    r = ArchiveReader(archive)
    vol = r.read_volume_meta("0007")
    assert vol["title"] == "Council Book"


def test_read_page_meta(archive):
    r = ArchiveReader(archive)
    meta = r.read_page_meta("0007", "cb_001.jpg")
    assert meta == {"resources": []}


def test_image_exists(archive):
    r = ArchiveReader(archive)
    assert r.image_exists("0007", "cb_001.jpg") is False
    (archive / "pages" / "0007" / "cb_001.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    assert r.image_exists("0007", "cb_001.jpg") is True


def test_read_names(archive):
    (archive / "pages" / "0007" / "cb_001.jpg.names.json").write_text(json.dumps(
        {"people": [["John Smith", "Jno. Smith"], ["Mary Doe"], []]}))
    r = ArchiveReader(archive)
    assert r.read_names("0007", "cb_001.jpg") == [
        ["John Smith", "Jno. Smith"], ["Mary Doe"]]


def test_read_names_missing_returns_empty(archive):
    r = ArchiveReader(archive)
    assert r.read_names("0007", "cb_001.jpg") == []


def test_read_and_write_notes(tmp_path):
    from vtextract.tui.archive_reader import ArchiveReader
    (tmp_path / "pages" / "v").mkdir(parents=True)
    r = ArchiveReader(tmp_path)
    assert r.read_notes("v", "p.jpg") == ""
    r.write_notes("v", "p.jpg", "hello")
    assert r.read_notes("v", "p.jpg") == "hello"
    r.write_notes("v", "p.jpg", " \n")   # whitespace-only removes the file
    assert not r.notes_path("v", "p.jpg").exists()
    r.write_notes("v", "p.jpg", "")      # nothing to create
    assert not r.notes_path("v", "p.jpg").exists()
