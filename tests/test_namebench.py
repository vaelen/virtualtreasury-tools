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
