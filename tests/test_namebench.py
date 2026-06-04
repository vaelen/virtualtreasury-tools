# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from pathlib import Path

from vtextract.namebench import BenchConfig, load_bench_config


def test_load_bench_config_parses_input_and_models(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        'input = "~/foo/bar"\n'
        'models = ["anthropic/claude-haiku-4-5", "openai/gpt-4.1-mini"]\n'
    )
    bc = load_bench_config(cfg)
    assert isinstance(bc, BenchConfig)
    assert bc.input == Path("~/foo/bar").expanduser()
    assert bc.models == ["anthropic/claude-haiku-4-5", "openai/gpt-4.1-mini"]


def test_load_bench_config_rejects_missing_input(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('models = ["m"]\n')
    try:
        load_bench_config(cfg)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "input" in str(exc)


def test_load_bench_config_rejects_empty_models(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('input = "."\nmodels = []\n')
    try:
        load_bench_config(cfg)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "models" in str(exc)


def test_load_bench_config_defaults_api_base_empty(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('input = "."\nmodels = ["m"]\n')
    assert load_bench_config(cfg).api_base == {}


def test_load_bench_config_parses_api_base_table(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        'input = "."\n'
        'models = ["anthropic/claude-haiku-4-5", "ollama/llama3"]\n'
        '\n[api_base]\n'
        '"ollama/llama3" = "http://localhost:11434"\n'
    )
    bc = load_bench_config(cfg)
    assert bc.api_base == {"ollama/llama3": "http://localhost:11434"}


def test_load_bench_config_rejects_non_table_api_base(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('input = "."\nmodels = ["m"]\napi_base = "http://x"\n')
    try:
        load_bench_config(cfg)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "api_base" in str(exc)


import json

from vtextract.namebench import (
    model_dir, sidecar_path, times_path, load_times, write_times, write_sidecar,
)
from vtextract.names.models import Person


def test_model_dir_nests_provider_and_model(tmp_path):
    md = model_dir(tmp_path, "anthropic/claude-haiku-4-5")
    assert md == tmp_path / "models" / "anthropic" / "claude-haiku-4-5"


def test_sidecar_and_times_paths(tmp_path):
    md = model_dir(tmp_path, "openai/gpt-4.1")
    assert sidecar_path(md, "1.txt").name == "1.txt.names.json"
    assert times_path(md).name == "times.json"


def test_write_and_load_times_roundtrip(tmp_path):
    md = model_dir(tmp_path, "m")
    md.mkdir(parents=True)
    write_times(md, {"1.txt": 1.5})
    assert load_times(md) == {"1.txt": 1.5}
    # missing file -> empty dict
    assert load_times(model_dir(tmp_path, "other")) == {}


def test_write_sidecar_shape(tmp_path):
    md = model_dir(tmp_path, "m")
    md.mkdir(parents=True)
    people = [Person(canonical="William Young",
                     aliases=[{"text": "Wm Young", "confidence": "high"}])]
    write_sidecar(sidecar_path(md, "1.txt"), "m", people)
    data = json.loads((md / "1.txt.names.json").read_text())
    assert data["schema"] == 1 and data["model"] == "m"
    assert data["people"][0]["canonical"] == "William Young"


from vtextract.namebench import extract_people


def _fake_find_factory(mapping):
    # mapping: chunk substring -> people list. Mirrors tests/names/test_extractor.py.
    def find(chunk_text, model, api_base=None):
        for needle, people in mapping.items():
            if needle in chunk_text:
                return people
        return []
    return find


def test_extract_people_merges_chunks():
    find = _fake_find_factory({
        "Wm Young": [Person(canonical="William Young",
                            aliases=[{"text": "Wm Young", "confidence": "high"}])],
    })
    people = extract_people("Wm Young paid the toll.", "m", find=find)
    assert [p.canonical for p in people] == ["William Young"]


def test_extract_people_propagates_chunk_failure():
    def boom(chunk_text, model, api_base=None):
        raise RuntimeError("bad json")
    try:
        extract_people("anything", "m", find=boom)
        assert False, "expected the failure to propagate"
    except Exception as exc:
        assert "bad json" in str(exc)


from vtextract.namebench import run_model


def _seed_inputs(tmp_path):
    (tmp_path / "1.txt").write_text("Wm Young paid the toll.")
    (tmp_path / "2.txt").write_text("nothing here")
    return tmp_path


def test_run_model_writes_sidecars_and_times(tmp_path):
    inp = _seed_inputs(tmp_path)
    find = _fake_find_factory({
        "Wm Young": [Person(canonical="William Young",
                            aliases=[{"text": "Wm Young", "confidence": "high"}])],
    })
    run_model(inp, "anthropic/claude-haiku-4-5", find=find)
    md = model_dir(inp, "anthropic/claude-haiku-4-5")
    assert (md / "1.txt.names.json").exists()
    assert (md / "2.txt.names.json").exists()
    times = load_times(md)
    assert set(times) == {"1.txt", "2.txt"}
    assert all(isinstance(v, (int, float)) and v >= 0 for v in times.values())


def test_run_model_skips_existing_and_preserves_time(tmp_path):
    inp = _seed_inputs(tmp_path)
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    # pre-existing sidecar + recorded time for 1.txt
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])
    write_times(md, {"1.txt": 99.0})

    calls = []
    def find(chunk_text, model, api_base=None):
        calls.append(chunk_text)
        return []
    run_model(inp, "m", find=find)
    # 1.txt skipped (find never saw its text); only 2.txt processed
    assert "Wm Young paid the toll." not in calls
    times = load_times(md)
    assert times["1.txt"] == 99.0          # preserved
    assert "2.txt" in times                # newly recorded


def test_run_model_force_reprocesses(tmp_path):
    inp = _seed_inputs(tmp_path)
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])

    seen = []
    def find(chunk_text, model, api_base=None):
        seen.append(chunk_text)
        return []
    run_model(inp, "m", find=find, force=True)
    assert any("Wm Young" in s for s in seen)  # 1.txt re-read despite sidecar


def test_run_model_logs_failure_and_continues(tmp_path, capsys):
    inp = _seed_inputs(tmp_path)
    def find(chunk_text, model, api_base=None):
        if "Wm Young" in chunk_text:
            raise RuntimeError("boom")
        return []
    run_model(inp, "m", find=find)
    md = model_dir(inp, "m")
    assert not (md / "1.txt.names.json").exists()   # failed file: no sidecar
    assert "1.txt" not in load_times(md)             # and no time entry
    assert (md / "2.txt.names.json").exists()        # other file still processed
    err = capsys.readouterr().err
    assert "1.txt" in err


from vtextract.namebench import discover_models, count_confidences, build_report


def test_count_confidences_buckets_persons_and_aliases():
    people = [
        Person(canonical="William Young", confidence="high",
               aliases=[{"text": "Wm Young", "confidence": "high"},
                        {"text": "Young", "confidence": "low"}]),
        Person(canonical="J. Smith", confidence="medium", aliases=[]),
    ]
    counts = count_confidences(people)
    # persons: high(William) + medium(J.Smith); aliases: high(Wm) + low(Young)
    assert counts == {"high": 2, "medium": 1, "low": 1}


def test_discover_models_finds_dirs_with_data(tmp_path):
    inp = tmp_path
    a = model_dir(inp, "anthropic/claude-haiku-4-5")
    a.mkdir(parents=True)
    write_sidecar(sidecar_path(a, "1.txt"), "anthropic/claude-haiku-4-5", [])
    b = model_dir(inp, "openai/gpt-4.1")
    b.mkdir(parents=True)
    write_times(b, {"1.txt": 2.0})           # has times but counted as data too
    empty = model_dir(inp, "openai/gpt-4.1-mini")
    empty.mkdir(parents=True)                  # no data -> excluded
    assert discover_models(inp) == [
        "anthropic/claude-haiku-4-5", "openai/gpt-4.1"]


def test_build_report_aggregates_per_model(tmp_path):
    inp = tmp_path
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [
        Person(canonical="William Young", confidence="high",
               aliases=[{"text": "Wm Young", "confidence": "high"}])])
    write_sidecar(sidecar_path(md, "2.txt"), "m", [])
    write_times(md, {"1.txt": 1.0, "2.txt": 3.0})
    rows = build_report(inp)
    assert len(rows) == 1
    row = rows[0]
    assert row.model == "m"
    assert row.files == 2
    assert row.high == 2 and row.medium == 0 and row.low == 0
    assert row.total == 2
    assert row.avg_seconds == 2.0


from vtextract.namebench import main


def test_main_processes_all_models_and_reports(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("Wm Young paid the toll.")
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        f'input = "{inp}"\n'
        'models = ["anthropic/claude-haiku-4-5", "openai/gpt-4.1"]\n'
    )
    find = _fake_find_factory({
        "Wm Young": [Person(canonical="William Young", confidence="high",
                            aliases=[{"text": "Wm Young", "confidence": "high"}])],
    })
    rc = main([str(cfg)], find=find)
    assert rc == 0
    # sidecars written for both models
    assert sidecar_path(model_dir(inp, "anthropic/claude-haiku-4-5"), "1.txt").exists()
    assert sidecar_path(model_dir(inp, "openai/gpt-4.1"), "1.txt").exists()
    out = capsys.readouterr().out
    assert "anthropic/claude-haiku-4-5" in out
    assert "openai/gpt-4.1" in out


def test_main_reports_unrun_model_with_existing_data(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    # prior-run data for a model NOT in this config
    old = model_dir(inp, "openai/gpt-4.1-mini")
    old.mkdir(parents=True)
    write_sidecar(sidecar_path(old, "1.txt"), "openai/gpt-4.1-mini",
                  [Person(canonical="A B", confidence="low", aliases=[])])
    write_times(old, {"1.txt": 5.0})
    cfg = tmp_path / "bench.toml"
    cfg.write_text(f'input = "{inp}"\nmodels = ["anthropic/claude-haiku-4-5"]\n')

    find = _fake_find_factory({})
    rc = main([str(cfg)], find=find)
    assert rc == 0
    out = capsys.readouterr().out
    # report includes the un-run prior-data model
    assert "openai/gpt-4.1-mini" in out


def test_main_errors_on_bad_config(tmp_path, capsys):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('models = ["m"]\n')   # missing input
    rc = main([str(cfg)], find=_fake_find_factory({}))
    assert rc != 0
    assert "input" in capsys.readouterr().err


def test_main_passes_per_model_api_base_to_find(tmp_path):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        f'input = "{inp}"\n'
        'models = ["anthropic/claude-haiku-4-5", "ollama/llama3"]\n'
        '\n[api_base]\n'
        '"ollama/llama3" = "http://localhost:11434"\n'
    )
    seen: dict[str, str | None] = {}

    def find(chunk_text, model, api_base=None):
        seen[model] = api_base
        return []
    rc = main([str(cfg)], find=find)
    assert rc == 0
    # listed model gets its endpoint; unlisted cloud model stays provider-routed
    assert seen["ollama/llama3"] == "http://localhost:11434"
    assert seen["anthropic/claude-haiku-4-5"] is None
