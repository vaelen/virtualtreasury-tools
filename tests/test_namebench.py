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
