# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract.names.extractor import extract, sidecar_for, page_transcriptions
from vtextract.names.models import Person


def _make_archive(tmp_path):
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "b.jpg.txt").write_text("nothing here")
    return tmp_path


def _fake_find_factory(mapping):
    # mapping: chunk substring -> people list
    def find(chunk_text, model, api_base=None):
        for needle, people in mapping.items():
            if needle in chunk_text:
                return people
        return []
    return find


def test_page_transcriptions_lists_pages(tmp_path):
    archive = _make_archive(tmp_path)
    found = {(r, k) for r, k, _ in page_transcriptions(archive)}
    assert found == {("100", "a.jpg"), ("100", "b.jpg")}


def test_sidecar_for_replaces_suffix(tmp_path):
    txt = tmp_path / "x.jpg.txt"
    assert sidecar_for(txt).name == "x.jpg.names.json"


def test_extract_writes_sidecars(tmp_path):
    archive = _make_archive(tmp_path)
    find = _fake_find_factory({"Wm Young": [Person(canonical="William Young",
                                                   aliases=[{"text": "Wm Young", "confidence": "high"}])]})
    stats = extract(archive, model="m", find=find, show_progress=False)
    assert stats.extracted == 2 and stats.skipped == 0 and stats.failed == 0
    assert stats.people == 1
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["schema"] == 1 and side["model"] == "m"
    assert side["people"][0]["canonical"] == "William Young"
    empty = json.loads((archive / "pages" / "100" / "b.jpg.names.json").read_text())
    assert empty["people"] == []


def test_extract_resumes_skipping_existing(tmp_path):
    archive = _make_archive(tmp_path)
    find = _fake_find_factory({})
    extract(archive, model="m", find=find, show_progress=False)
    # second run: all sidecars present -> all skipped
    stats = extract(archive, model="m", find=find, show_progress=False)
    assert stats.skipped == 2 and stats.extracted == 0


def test_extract_force_overwrites(tmp_path):
    archive = _make_archive(tmp_path)
    extract(archive, model="m", find=_fake_find_factory({}), show_progress=False)
    stats = extract(archive, model="m", find=_fake_find_factory({}), force=True, show_progress=False)
    assert stats.extracted == 2 and stats.skipped == 0


def test_extract_failure_leaves_no_sidecar(tmp_path):
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None):
        raise RuntimeError("model down")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed == 2 and stats.extracted == 0
    assert not (archive / "pages" / "100" / "a.jpg.names.json").exists()


def test_extract_scope_limits_pages(tmp_path):
    archive = _make_archive(tmp_path)
    stats = extract(archive, model="m", find=_fake_find_factory({}),
                    scope_pages={("100", "a.jpg")}, show_progress=False)
    assert stats.extracted == 1
    assert (archive / "pages" / "100" / "a.jpg.names.json").exists()
    assert not (archive / "pages" / "100" / "b.jpg.names.json").exists()
