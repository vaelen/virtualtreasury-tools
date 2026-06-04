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
from vtextract.names.models import Person, Usage


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
    assert "usage" not in data   # no usage passed -> no block


def test_write_sidecar_includes_usage_block(tmp_path):
    md = model_dir(tmp_path, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [],
                  usage=Usage(input=100, output=20, cached=64))
    data = json.loads((md / "1.txt.names.json").read_text())
    assert data["usage"] == {"in": 100, "out": 20, "total": 120, "cached": 64}


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
    people, usage = extract_people("Wm Young paid the toll.", "m", find=find)
    assert [p.canonical for p in people] == ["William Young"]
    assert usage is None   # bare-list fake reports no usage


def test_extract_people_sums_usage_across_chunks():
    def find(chunk_text, model, api_base=None):
        return [Person(canonical="A")], Usage(input=50, output=10, cached=8)

    # chunk_size/overlap chosen so the text splits into two windows
    people, usage = extract_people(
        "A" * 30, "m", chunk_size=20, overlap=5, find=find)
    assert usage.input == 100 and usage.output == 20 and usage.cached == 16


def test_extract_people_propagates_chunk_failure():
    def boom(chunk_text, model, api_base=None):
        raise RuntimeError("bad json")
    try:
        extract_people("anything", "m", find=boom)
        assert False, "expected the failure to propagate"
    except Exception as exc:
        assert "bad json" in str(exc)


from vtextract.namebench import run_model, WARMUP_TEXT


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
    run_model(inp, "anthropic/claude-haiku-4-5", find=find, show_progress=False)
    md = model_dir(inp, "anthropic/claude-haiku-4-5")
    assert (md / "1.txt.names.json").exists()
    assert (md / "2.txt.names.json").exists()
    times = load_times(md)
    assert set(times) == {"1.txt", "2.txt"}
    assert all(isinstance(v, (int, float)) and v >= 0 for v in times.values())


def test_run_model_warms_up_before_timed_files(tmp_path):
    inp = _seed_inputs(tmp_path)   # 1.txt, 2.txt
    seen = []
    def find(chunk_text, model, api_base=None):
        seen.append(chunk_text)
        return []
    run_model(inp, "m", find=find, show_progress=False)
    md = model_dir(inp, "m")
    # the warm-up document is sent FIRST, before any real input file
    assert seen[0] == WARMUP_TEXT
    # ...but it is neither timed nor written as a sidecar
    assert set(load_times(md)) == {"1.txt", "2.txt"}   # no warm-up time entry
    assert sorted(p.name for p in md.glob("*.names.json")) == [
        "1.txt.names.json", "2.txt.names.json"]        # no warm-up sidecar


def test_run_model_no_warmup_when_nothing_to_do(tmp_path):
    inp = _seed_inputs(tmp_path)
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])
    write_sidecar(sidecar_path(md, "2.txt"), "m", [])   # everything already done
    seen = []
    def find(chunk_text, model, api_base=None):
        seen.append(chunk_text)
        return []
    run_model(inp, "m", find=find, show_progress=False)
    assert seen == []   # nothing to process -> no warm-up call either


def test_run_model_warmup_failure_does_not_abort(tmp_path):
    inp = _seed_inputs(tmp_path)
    calls = []
    def find(chunk_text, model, api_base=None):
        calls.append(chunk_text)
        if chunk_text == WARMUP_TEXT:
            raise RuntimeError("cold start blew up")
        return []
    run_model(inp, "m", find=find, show_progress=False)
    md = model_dir(inp, "m")
    # warm-up raised but was swallowed; the real files still processed
    assert calls[0] == WARMUP_TEXT
    assert (md / "1.txt.names.json").exists()
    assert (md / "2.txt.names.json").exists()


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
    run_model(inp, "m", find=find, show_progress=False)
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
    run_model(inp, "m", find=find, force=True, show_progress=False)
    assert any("Wm Young" in s for s in seen)  # 1.txt re-read despite sidecar


def test_run_model_logs_failure_and_continues(tmp_path, capsys):
    inp = _seed_inputs(tmp_path)
    def find(chunk_text, model, api_base=None):
        if "Wm Young" in chunk_text:
            raise RuntimeError("boom")
        return []
    run_model(inp, "m", find=find, show_progress=False)
    md = model_dir(inp, "m")
    assert not (md / "1.txt.names.json").exists()   # failed file: no sidecar
    assert "1.txt" not in load_times(md)             # and no time entry
    assert (md / "2.txt.names.json").exists()        # other file still processed
    err = capsys.readouterr().err
    assert "1.txt" in err


def test_run_model_renders_progress_bar(tmp_path, capsys):
    inp = _seed_inputs(tmp_path)
    # show_progress defaults True -> a Rich bar labelled with the model is drawn
    run_model(inp, "anthropic/claude-haiku-4-5", find=_fake_find_factory({}))
    err = capsys.readouterr().err
    assert "anthropic/claude-haiku-4-5" in err   # bar description names the model
    assert "100%" in err                          # bar completed over the files


from vtextract.namebench import (
    discover_models, count_names, normalize_name, build_report,
)


def test_normalize_name_strips_titles_and_punctuation():
    assert normalize_name("Mr. William Young, Esq.") == "william young"
    assert normalize_name("Capt. Skinner") == "skinner"
    assert normalize_name("J. Smith") == "j smith"
    # same person, different surface forms collapse to one key
    assert normalize_name("Widow Burton") == normalize_name("burton")


def test_count_names_counts_persons_and_aliases():
    people = [
        Person(canonical="William Young", confidence="high",
               aliases=[{"text": "Wm Young", "confidence": "high"},
                        {"text": "Young", "confidence": "low"}]),
        Person(canonical="J. Smith", confidence="medium", aliases=[]),
    ]
    # 2 persons; 2 aliases (both on William Young, none on J. Smith)
    assert count_names(people) == (2, 2)


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
    # input files of known sizes for the length-normalized (ms/byte) metric
    (inp / "1.txt").write_text("x" * 100)
    (inp / "2.txt").write_text("x" * 300)
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [
        Person(canonical="William Young", confidence="high",
               aliases=[{"text": "Wm Young", "confidence": "high"},
                        {"text": "Young", "confidence": "low"}]),
        Person(canonical="J. Smith", confidence="medium", aliases=[])],
        usage=Usage(input=100, output=20, cached=64))
    write_sidecar(sidecar_path(md, "2.txt"), "m", [],
                  usage=Usage(input=40, output=2, cached=0))   # an "empty" extraction
    write_times(md, {"1.txt": 1.0, "2.txt": 3.0})
    rows = build_report(inp)
    assert len(rows) == 1
    row = rows[0]
    assert row.model == "m"
    assert row.files == 2
    assert row.empty_files == 1            # 2.txt produced no persons
    assert row.persons == 2                # William Young + J. Smith
    assert row.aliases == 2                # both on William Young
    assert row.aliases_per_person == 1.0   # 2 aliases / 2 persons
    assert row.persons_per_file == 1.0     # 2 persons / 2 files
    # P/R/F1 need cross-model consensus; with a single model there is none
    assert row.precision is None and row.recall is None and row.f1 is None
    # timing distribution
    assert row.min_s == 1.0
    assert row.max_s == 3.0
    assert row.median_s == 2.0
    assert row.mean_s == 2.0
    # ms/byte = (1.0 + 3.0) s * 1000 / (100 + 300) bytes = 10.0
    assert row.ms_per_byte == 10.0
    # s/name = (1.0 + 3.0) s / 2 persons = 2.0 (latency is output-bound)
    assert row.s_per_name == 2.0
    # token usage summed across both sidecars
    assert row.tokens_in == 140 and row.tokens_out == 22 and row.tokens_cached == 64


def test_build_report_tokens_none_when_no_usage_recorded(tmp_path):
    """Older sidecars without a usage block report n/a, not a misleading 0."""
    inp = tmp_path
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])   # no usage= arg -> no block
    row = build_report(inp)[0]
    assert row.tokens_in is None
    assert row.tokens_out is None
    assert row.tokens_cached is None


def test_build_report_ratios_none_without_data(tmp_path):
    inp = tmp_path
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])   # sidecar, no persons, no times
    row = build_report(inp)[0]
    assert row.persons == 0 and row.aliases == 0
    assert row.empty_files == 1
    assert row.aliases_per_person is None   # no persons -> undefined
    assert row.persons_per_file == 0.0      # 0 persons / 1 file
    assert row.precision is None and row.recall is None and row.f1 is None
    assert row.min_s is None and row.max_s is None
    assert row.median_s is None and row.mean_s is None
    assert row.ms_per_byte is None
    assert row.s_per_name is None           # no persons (and no times) -> undefined


def test_build_report_precision_recall_against_consensus(tmp_path):
    inp = tmp_path
    (inp / "1.txt").write_text("doc")

    def seed(model, names):
        md = model_dir(inp, model)
        md.mkdir(parents=True)
        write_sidecar(sidecar_path(md, "1.txt"), model,
                      [Person(canonical=n, confidence="high", aliases=[])
                       for n in names])

    # 3 models, majority = 2. Consensus truth = {John Smith, Mary Jones}.
    # "Ghost" (only model a) is a singleton -> excluded, a false positive for a.
    seed("a", ["John Smith", "Mary Jones", "Ghost"])
    seed("b", ["John Smith", "Mary Jones"])
    seed("c", ["John Smith"])
    rows = {r.model: r for r in build_report(inp)}

    # a: found 3, hits 2 -> P = 2/3, R = 2/2 = 1.0
    assert rows["a"].precision == 2 / 3
    assert rows["a"].recall == 1.0
    # b: found 2, both consensus -> P = R = F1 = 1.0
    assert rows["b"].precision == 1.0 and rows["b"].recall == 1.0
    assert rows["b"].f1 == 1.0
    # c: found 1 (John Smith), hits 1 -> P = 1.0, R = 1/2 = 0.5
    assert rows["c"].precision == 1.0
    assert rows["c"].recall == 0.5
    assert abs(rows["c"].f1 - (2 * 1.0 * 0.5 / 1.5)) < 1e-9


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


def test_main_announces_file_count_before_models(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    for i in range(1, 4):
        (inp / f"{i}.txt").write_text("hi")
    cfg = tmp_path / "bench.toml"
    cfg.write_text(f'input = "{inp}"\nmodels = ["anthropic/claude-haiku-4-5"]\n')
    main([str(cfg)], find=_fake_find_factory({}))
    assert "Found 3 files" in capsys.readouterr().err


def test_main_announces_each_model_to_stderr(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        f'input = "{inp}"\n'
        'models = ["anthropic/claude-haiku-4-5", "openai/gpt-4.1"]\n'
    )
    main([str(cfg)], find=_fake_find_factory({}))
    err = capsys.readouterr().err
    # each model is announced as it is tested (progress goes to stderr so the
    # report on stdout stays clean/pipeable)
    assert "anthropic/claude-haiku-4-5" in err
    assert "openai/gpt-4.1" in err


def test_main_announces_skip_when_all_done(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])   # already processed
    cfg = tmp_path / "bench.toml"
    cfg.write_text(f'input = "{inp}"\nmodels = ["m"]\n')

    calls = []
    def find(chunk_text, model, api_base=None):
        calls.append(chunk_text)
        return []
    main([str(cfg)], find=find)
    err = capsys.readouterr().err
    assert "all 1 already done, skipping" in err
    assert calls == []   # nothing was re-processed


def test_main_announces_pending_and_done_split(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    (inp / "2.txt").write_text("yo")
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])   # 1 done, 1 pending
    cfg = tmp_path / "bench.toml"
    cfg.write_text(f'input = "{inp}"\nmodels = ["m"]\n')
    main([str(cfg)], find=_fake_find_factory({}))
    err = capsys.readouterr().err
    assert "1 to process, 1 already done" in err


# --- model lifecycle (warm-up + unload) -----------------------------------
# These exercise the production path (find=None), monkeypatching the LLM
# choke-point functions so nothing touches the network.

def test_main_warms_up_then_unloads_local_models(tmp_path, monkeypatch):
    import vtextract.names.llm as llm
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        f'input = "{inp}"\n'
        'models = ["ollama/a", "ollama/b"]\n'
        '\n[api_base]\n'
        '"ollama/a" = "http://localhost:11434"\n'
        '"ollama/b" = "http://localhost:11434"\n'
    )
    warmed: list[str] = []
    unloaded: list[str] = []
    monkeypatch.setattr(llm, "find_people", lambda chunk, model, api_base=None: [])
    monkeypatch.setattr(llm, "check_model",
                        lambda model, api_base=None: warmed.append(model) or None)
    monkeypatch.setattr(llm, "unload",
                        lambda model, api_base=None: unloaded.append(model))

    rc = main([str(cfg)])   # find=None -> production lifecycle path
    assert rc == 0
    assert warmed == ["ollama/a", "ollama/b"]      # each warmed before its files
    # a is evicted before b loads; b is evicted at the end
    assert unloaded == ["ollama/a", "ollama/b"]


def test_main_skips_model_when_preflight_fails(tmp_path, monkeypatch, capsys):
    import vtextract.names.llm as llm
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    cfg = tmp_path / "bench.toml"
    cfg.write_text(f'input = "{inp}"\nmodels = ["openai/x"]\n')

    processed: list[str] = []
    monkeypatch.setattr(llm, "find_people",
                        lambda chunk, model, api_base=None: processed.append(model) or [])
    monkeypatch.setattr(llm, "check_model",
                        lambda model, api_base=None: "Authentication failed for 'openai/x'.")
    monkeypatch.setattr(llm, "unload", lambda model, api_base=None: None)

    rc = main([str(cfg)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "skipping openai/x" in err
    assert processed == []   # files never processed when preflight fails
    assert not sidecar_path(model_dir(inp, "openai/x"), "1.txt").exists()
