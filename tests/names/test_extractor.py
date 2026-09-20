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
    def find(chunk_text, model, api_base=None, notes=None):
        for needle, people in mapping.items():
            if needle in chunk_text:
                return people
        return []
    return find


def test_extract_forwards_max_output_tokens_to_production_find(tmp_path, monkeypatch):
    # When no find seam is injected (production), extract must bind the configured
    # output cap into the real find_people so the guardrail actually reaches the
    # provider. Tests still inject their own 3-arg find and are unaffected.
    from vtextract.names import llm as llm_module
    seen = {}

    def fake_find_people(chunk_text, model, api_base=None, *, max_output_tokens=None,
                         notes=None):
        seen["max_output_tokens"] = max_output_tokens
        return [], Usage(input=1, output=1)

    monkeypatch.setattr(llm_module, "find_people", fake_find_people)
    archive = _make_archive(tmp_path)
    extract(archive, model="m", max_output_tokens=9000, show_progress=False)
    assert seen["max_output_tokens"] == 9000


def test_large_page_is_split_into_dense_chunks(tmp_path):
    # A page over dense_threshold must be chunked at dense_chunk_size, so a dense
    # page reaches the model as several short generations instead of one long
    # (loop-prone) one. A small page stays a single chunk.
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "big.jpg.txt").write_text("x" * 7000)
    (pages / "small.jpg.txt").write_text("x" * 3000)

    windows: dict[str, list[int]] = {}

    def find(chunk_text, model, api_base=None, notes=None):
        windows.setdefault(model, [])
        windows[model].append(len(chunk_text))
        return []

    extract(tmp_path, model="m", find=find, show_progress=False,
            dense_threshold=5000, dense_chunk_size=3000, overlap=0)
    sizes = sorted(windows["m"])
    # big (7000) -> 3 chunks of <=3000; small (3000) -> 1 chunk of 3000
    assert sizes == [1000, 3000, 3000, 3000]
    assert max(sizes) <= 3000


def test_small_pages_stay_single_chunk_by_default(tmp_path):
    archive = _make_archive(tmp_path)  # tiny pages, well under any threshold
    calls = []

    def find(chunk_text, model, api_base=None, notes=None):
        calls.append(chunk_text)
        return []

    extract(archive, model="m", find=find, show_progress=False)
    assert len(calls) == 2  # one call per page, not split


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
                                                   aliases=["Wm Young"])]})
    stats = extract(archive, model="m", find=find, show_progress=False)
    assert stats.extracted == 2 and stats.skipped == 0 and stats.failed == 0
    assert stats.people == 1
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["schema"] == 2 and side["model"] == "m"
    assert side["people"][0] == ["William Young", "Wm Young"]
    empty = json.loads((archive / "pages" / "100" / "b.jpg.names.json").read_text())
    assert empty["people"] == []
    # a bare-list find reports no usage, so no usage block is written
    assert "usage" not in side


def test_extract_writes_usage_block_when_find_reports_it(tmp_path):
    archive = _make_archive(tmp_path)

    def find(chunk_text, model, api_base=None, notes=None):
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

    def slow_find(chunk_text, model, api_base=None, notes=None):
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

    def boom(chunk_text, model, api_base=None, notes=None):
        raise RuntimeError("model down")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed == 2 and stats.extracted == 0
    assert not (archive / "pages" / "100" / "a.jpg.names.json").exists()


def test_extract_failure_logs_reason_to_stderr(tmp_path, capsys):
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None, notes=None):
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

    def find(chunk_text, model, api_base=None, notes=None):
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


def test_error_sidecar_for_replaces_suffix(tmp_path):
    from vtextract.names.extractor import error_sidecar_for
    txt = tmp_path / "x.jpg.txt"
    assert error_sidecar_for(txt).name == "x.jpg.names.error.json"


def test_write_error_sidecar_increments_attempts(tmp_path):
    from vtextract.names.extractor import error_sidecar_for, _write_error_sidecar
    txt = tmp_path / "x.jpg.txt"
    txt.write_text("body")
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="cut off")
    data = json.loads(error_sidecar_for(txt).read_text())
    assert data["schema"] == 1
    assert data["model"] == "m"
    assert data["error_class"] == "truncated"
    assert data["finish_reason"] == "length"
    assert data["attempts"] == 1
    assert data["message"] == "cut off"
    assert data["last_attempt"].endswith("Z")
    # second write for the same page bumps the counter
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="cut off again")
    data2 = json.loads(error_sidecar_for(txt).read_text())
    assert data2["attempts"] == 2


def test_persistent_failure_writes_error_sidecar(tmp_path):
    from vtextract.names.extractor import extract, error_sidecar_for, sidecar_for
    from vtextract.names.llm import TruncatedResponseError
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None, notes=None):
        raise TruncatedResponseError(
            "response truncated at output-token limit (finish_reason=length)",
            finish_reason="length")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed_persistent == 2
    assert stats.failed == 0
    err = error_sidecar_for(archive / "pages" / "100" / "a.jpg.txt")
    assert err.exists()
    assert json.loads(err.read_text())["error_class"] == "truncated"
    # no success sidecar written
    assert not sidecar_for(archive / "pages" / "100" / "a.jpg.txt").exists()


def test_transient_failure_writes_no_error_sidecar(tmp_path):
    from vtextract.names.extractor import extract, error_sidecar_for
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None, notes=None):
        raise ConnectionError("connection refused")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed == 2
    assert stats.failed_persistent == 0
    assert not error_sidecar_for(archive / "pages" / "100" / "a.jpg.txt").exists()


def test_parked_page_skipped_on_normal_run(tmp_path):
    from vtextract.names.extractor import extract, sidecar_for, _write_error_sidecar
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="old")

    def fail_if_called(chunk_text, model, api_base=None, notes=None):
        raise AssertionError("parked page must not be re-attempted")

    stats = extract(archive, model="m", find=fail_if_called, show_progress=False)
    # a.jpg is parked (skipped); b.jpg has no sidecar and is processed
    assert stats.parked == 1
    assert not sidecar_for(txt).exists()


def test_retry_failed_reattempts_parked_page(tmp_path):
    from vtextract.names.extractor import (
        extract, sidecar_for, error_sidecar_for, _write_error_sidecar)
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="old")
    stats = extract(archive, model="m", find=_fake_find_factory({}),
                    retry_failed=True, show_progress=False)
    assert stats.parked == 0
    assert sidecar_for(txt).exists()            # now succeeded
    assert not error_sidecar_for(txt).exists()  # stale error cleared


def test_skip_as_done_clears_orphan_error_sidecar(tmp_path):
    from vtextract.names.extractor import (
        extract, sidecar_for, error_sidecar_for, _write_error_sidecar)
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    # both a success sidecar AND a stale error sidecar exist for the same page
    extract(archive, model="m", find=_fake_find_factory({}), show_progress=False)
    _write_error_sidecar(txt, model="m", error_class="bad_json",
                         finish_reason=None, message="stale")
    assert error_sidecar_for(txt).exists()
    stats = extract(archive, model="m", find=_fake_find_factory({}),
                    show_progress=False)
    assert stats.skipped == 2
    assert not error_sidecar_for(txt).exists()  # success wins, orphan removed


def test_success_removes_stale_error_sidecar(tmp_path):
    from vtextract.names.extractor import (
        extract, error_sidecar_for, _write_error_sidecar)
    archive = _make_archive(tmp_path)
    txt = archive / "pages" / "100" / "a.jpg.txt"
    _write_error_sidecar(txt, model="m", error_class="truncated",
                         finish_reason="length", message="old")
    assert error_sidecar_for(txt).exists()
    # force so the page is reprocessed even though no success sidecar exists yet
    extract(archive, model="m", find=_fake_find_factory({}), force=True,
            show_progress=False)
    assert not error_sidecar_for(txt).exists()


def test_iter_error_sidecars_returns_records(tmp_path):
    from vtextract.names.extractor import iter_error_sidecars, _write_error_sidecar
    archive = _make_archive(tmp_path)
    _write_error_sidecar(archive / "pages" / "100" / "a.jpg.txt", model="m",
                         error_class="truncated", finish_reason="length",
                         message="cut off")
    records = iter_error_sidecars(archive)
    assert len(records) == 1
    rec = records[0]
    assert rec.root_id == "100"
    assert rec.page_key == "a.jpg"
    assert rec.error_class == "truncated"
    assert rec.attempts == 1
    assert rec.message == "cut off"


def test_iter_error_sidecars_honours_scope(tmp_path):
    from vtextract.names.extractor import iter_error_sidecars, _write_error_sidecar
    archive = _make_archive(tmp_path)
    for key in ("a.jpg", "b.jpg"):
        _write_error_sidecar(archive / "pages" / "100" / f"{key}.txt", model="m",
                             error_class="bad_json", finish_reason=None, message="x")
    scoped = iter_error_sidecars(archive, scope_pages={("100", "a.jpg")})
    assert {r.page_key for r in scoped} == {"a.jpg"}


def test_extract_passes_page_notes_to_find(tmp_path):
    # A <page_key>.notes.md beside the transcription reaches the find seam as
    # ``notes``; pages without one get None.
    archive = _make_archive(tmp_path)
    (archive / "pages" / "100" / "a.jpg.notes.md").write_text("J. Smith is James Smith.\n")
    seen = {}

    def find(chunk_text, model, api_base=None, notes=None):
        seen[chunk_text] = notes
        return []

    extract(archive, model="m", find=find, show_progress=False)
    assert seen["Wm Young paid the toll."] == "J. Smith is James Smith.\n"
    assert seen["nothing here"] is None


def test_extract_forwards_notes_to_production_find(tmp_path, monkeypatch):
    from vtextract.names import llm as llm_module
    seen = {}

    def fake_find_people(chunk_text, model, api_base=None, *, max_output_tokens=None,
                         notes=None):
        seen[chunk_text] = notes
        return [], Usage(input=1, output=1)

    monkeypatch.setattr(llm_module, "find_people", fake_find_people)
    archive = _make_archive(tmp_path)
    (archive / "pages" / "100" / "a.jpg.notes.md").write_text("notes here")
    extract(archive, model="m", show_progress=False)
    assert seen["Wm Young paid the toll."] == "notes here"
    assert seen["nothing here"] is None
