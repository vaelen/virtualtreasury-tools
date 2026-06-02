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
        return [Person(canonical="William Young",
                       aliases=[{"text": "Wm Young", "confidence": "high"}])]

    monkeypatch.setattr(cli, "_make_find", lambda: fake_find)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg)])
    assert rc == 0
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["people"][0]["canonical"] == "William Young"


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


def test_names_command_no_pages_returns_zero(tmp_path, monkeypatch):
    archive = tmp_path
    (archive / "pages").mkdir()
    cfg = tmp_path / "vt.toml"
    cfg.write_text("")
    monkeypatch.setattr(cli, "_make_find", lambda: (lambda *a, **k: []))
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg)])
    assert rc == 0
