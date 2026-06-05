# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract.names.extractor import extract, sidecar_for, page_transcriptions
from vtextract.names.models import Person, Usage


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
    # a bare-list find reports no usage, so no usage block is written
    assert "usage" not in side


def test_extract_writes_usage_block_when_find_reports_it(tmp_path):
    archive = _make_archive(tmp_path)

    def find(chunk_text, model, api_base=None):
        people = [Person(canonical="William Young")] if "Wm Young" in chunk_text else []
        return people, Usage(input=100, output=20, cached=64)

    extract(archive, model="m", find=find, show_progress=False)
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["usage"] == {"in": 100, "out": 20, "total": 120, "cached": 64}


def test_extract_writes_elapsed_ms(tmp_path):
    # elapsed_ms is always written (we measure it ourselves), even when the
    # find seam reports no token usage.
    archive = _make_archive(tmp_path)
    extract(archive, model="m", find=_fake_find_factory({}), show_progress=False)
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert "usage" not in side
    assert isinstance(side["elapsed_ms"], int) and side["elapsed_ms"] >= 0


def test_extract_elapsed_ms_reflects_extraction_time(tmp_path):
    import time as _time

    archive = _make_archive(tmp_path)

    def slow_find(chunk_text, model, api_base=None):
        _time.sleep(0.02)
        return []

    extract(archive, model="m", find=slow_find, show_progress=False)
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["elapsed_ms"] >= 15


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


def test_extract_failure_logs_reason_to_stderr(tmp_path, capsys):
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None):
        raise RuntimeError("model down")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed == 2
    err = capsys.readouterr().err
    # each failed page is named, with the underlying reason surfaced
    assert "a.jpg" in err and "b.jpg" in err
    assert "model down" in err


def test_extract_partial_chunk_failure_fails_whole_page(tmp_path):
    # A page that splits into >1 chunk where one chunk's call fails must NOT
    # write a degraded sidecar, or the page looks done and never gets retried.
    archive = tmp_path
    pages = archive / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "long.jpg.txt").write_text("AAAA BBBB")  # two chunks at chunk_size=5

    def find(chunk_text, model, api_base=None):
        if "BBBB" in chunk_text:
            raise RuntimeError("chunk down")
        return [Person(canonical="A A")]

    stats = extract(archive, model="m", find=find, chunk_size=5, overlap=0,
                    show_progress=False)
    assert stats.failed == 1 and stats.extracted == 0
    assert not (pages / "long.jpg.names.json").exists()


def test_extract_scope_limits_pages(tmp_path):
    archive = _make_archive(tmp_path)
    stats = extract(archive, model="m", find=_fake_find_factory({}),
                    scope_pages={("100", "a.jpg")}, show_progress=False)
    assert stats.extracted == 1
    assert (archive / "pages" / "100" / "a.jpg.names.json").exists()
    assert not (archive / "pages" / "100" / "b.jpg.names.json").exists()
