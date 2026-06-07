# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract import cli
from vtextract.names.models import Person


def _archive_with_page(tmp_path):
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    cfg = tmp_path / "vt.toml"
    cfg.write_text('[names]\nmodel = "test/model"\n')
    return tmp_path, cfg


def test_names_command_writes_sidecar(tmp_path, monkeypatch):
    archive, cfg = _archive_with_page(tmp_path)

    def fake_find(chunk_text, model, api_base=None):
        assert model == "test/model"
        return [Person(canonical="William Young", aliases=["Wm Young"])]

    monkeypatch.setattr(cli, "_make_find", lambda: fake_find)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg)])
    assert rc == 0
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["people"][0] == ["William Young", "Wm Young"]


def test_names_command_model_override(tmp_path, monkeypatch):
    archive, cfg = _archive_with_page(tmp_path)
    seen = {}

    def fake_find(chunk_text, model, api_base=None):
        seen["model"] = model
        return []

    monkeypatch.setattr(cli, "_make_find", lambda: fake_find)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--model", "ollama/llama3.1"])
    assert rc == 0
    assert seen["model"] == "ollama/llama3.1"


def test_names_command_scopes_to_identifier_pages(tmp_path, monkeypatch):
    """Passing an item identifier limits extraction to that item's pages
    (vtextract.names.extractor.pages_for_resources scoping)."""
    # Two page transcriptions in the same volume; only one belongs to the item.
    pages = tmp_path / "pages" / "volA"
    pages.mkdir(parents=True)
    (pages / "p1.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "p2.jpg.txt").write_text("Someone else entirely.")

    item = tmp_path / "items" / "474234"
    item.mkdir(parents=True)
    (item / "metadata.json").write_text(json.dumps({
        "isadgID": 474234,
        "referenceCode": "TNA SO 1/14",
        "pages": [
            {"root_id": "volA", "page_key": "p1.jpg", "role": "primary"},
        ],
    }))

    cfg = tmp_path / "vt.toml"
    cfg.write_text('[names]\nmodel = "test/model"\n')

    monkeypatch.setattr(cli, "_make_find", lambda: (lambda *a, **k: []))
    rc = cli.run(["names", "474234", "--archive", str(tmp_path), "--config", str(cfg)])
    assert rc == 0
    # Sidecar written only for the item's page.
    assert (pages / "p1.jpg.names.json").exists()
    assert not (pages / "p2.jpg.names.json").exists()


def test_names_help_epilog_shows_config_and_examples(tmp_path, capsys):
    cfg = tmp_path / "vt.toml"
    cfg.write_text('[names]\nmodel = "test/model"\nworkers = 4\n')
    with pytest.raises(SystemExit) as exc:
        cli.run(["names", "--config", str(cfg), "-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Reflects the configured model and worker count.
    assert "test/model" in out
    assert "4 workers" in out  # pluralized
    # Explains where/how to set the model.
    assert "[names]" in out
    assert "vt.toml" in out
    # Example models: a local llama, Anthropic Haiku, an OpenAI model.
    assert "llama3.1" in out
    assert "haiku" in out
    assert "openai/" in out


def test_names_help_epilog_defaults_without_config(tmp_path, capsys):
    """With no [names] config, the epilog shows the built-in default model."""
    cfg = tmp_path / "vt.toml"
    cfg.write_text("")
    with pytest.raises(SystemExit) as exc:
        cli.run(["names", "--config", str(cfg), "-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "ollama/llama3.1" in out
    assert "1 worker" in out
    assert "1 workers" not in out  # singular, not pluralized


def test_names_command_no_pages_returns_zero(tmp_path, monkeypatch):
    archive = tmp_path
    (archive / "pages").mkdir()
    cfg = tmp_path / "vt.toml"
    cfg.write_text("")
    monkeypatch.setattr(cli, "_make_find", lambda: (lambda *a, **k: []))
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg)])
    assert rc == 0


def test_names_retry_failed_flag_passed_through(tmp_path, monkeypatch):
    from vtextract.names import extractor as names_extractor

    archive, cfg = _archive_with_page(tmp_path)
    captured = {}

    def fake_extract(arch, **kwargs):
        captured.update(kwargs)
        return names_extractor.NamesStats()

    monkeypatch.setattr(names_extractor, "extract", fake_extract)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--retry-failed"])
    assert rc == 0
    assert captured["retry_failed"] is True


def test_names_list_failed_prints_rows_without_llm(tmp_path, monkeypatch, capsys):
    from vtextract.names import extractor as names_extractor

    archive, cfg = _archive_with_page(tmp_path)

    def fail_if_called():
        raise AssertionError("--list-failed must not build a find/LLM seam")

    monkeypatch.setattr(cli, "_make_find", fail_if_called)
    names_extractor._write_error_sidecar(
        archive / "pages" / "100" / "a.jpg.txt", model="m",
        error_class="truncated", finish_reason="length", message="cut off")
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--list-failed"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "a.jpg" in out
    assert "truncated" in out


def test_names_list_failed_empty_is_clean(tmp_path, capsys):
    archive, cfg = _archive_with_page(tmp_path)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--list-failed"])
    assert rc == 0
    assert "no parked" in capsys.readouterr().out.lower()
