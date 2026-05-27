# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
import shutil
from pathlib import Path

from vtextract.index.cli import main

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def _archive(tmp_path) -> Path:
    dest = tmp_path / "archive"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_build_then_search_json_match(tmp_path, capsys):
    archive = _archive(tmp_path)
    assert main(["build", "--archive", str(archive)]) == 0
    capsys.readouterr()
    code = main(["search", "Houston", "--in", "title", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert [r["isadg_id"] for r in payload] == [100]
    assert payload[0]["matched_fields"] == ["title"]


def test_search_no_match_exit_1(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "zzznotfound", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert json.loads(out) == []


def test_search_missing_index_exit_2(tmp_path, capsys):
    archive = _archive(tmp_path)  # never built
    code = main(["search", "Houston", "--archive", str(archive)])
    err = capsys.readouterr().err
    assert code == 2
    assert "build" in err.lower()


def test_volumes_json(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["volumes", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    roots = sorted(v["root_id"] for v in payload)
    assert roots == ["volA", "volB"]


def test_stats_json(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["stats", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["items"] == 3
    assert payload["stale"] is False


def test_date_and_volume_filters(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "--from", "1689", "--to", "1689",
                 "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [r["isadg_id"] for r in payload] == [300]


def test_archive_from_config(tmp_path, capsys):
    archive = _archive(tmp_path)
    config = tmp_path / "vt.toml"
    config.write_text(f'archive = "{archive}"\n')
    assert main(["build", "--config", str(config)]) == 0
    capsys.readouterr()
    assert main(
        ["search", "Houston", "--in", "title", "--json", "--config", str(config)]
    ) == 0


def test_stale_index_warns(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    # add a new item after build -> archive changed -> stale
    (archive / "items" / "400").mkdir()
    shutil.copy(archive / "items" / "300" / "metadata.json",
                archive / "items" / "400" / "metadata.json")
    code = main(["search", "Galway", "--in", "title", "--archive", str(archive), "--json"])
    err = capsys.readouterr().err
    assert code == 0
    assert "stale" in err.lower() or "build" in err.lower()


def test_build_missing_archive_exit_2(tmp_path, capsys):
    code = main(["build", "--archive", str(tmp_path / "does_not_exist")])
    err = capsys.readouterr().err
    assert code == 2
    assert "archive" in err.lower()


def test_build_all_skipped_exit_2(tmp_path, capsys):
    archive = tmp_path / "archive"
    (archive / "items" / "999").mkdir(parents=True)
    (archive / "items" / "999" / "metadata.json").write_text("{ not json")
    code = main(["build", "--archive", str(archive)])
    err = capsys.readouterr().err
    assert code == 2
    assert "skipped" in err.lower()


def test_no_command_prints_help_exit_2(capsys):
    code = main([])
    err = capsys.readouterr().err
    assert code == 2
    assert "usage: vtindex" in err
    assert "build" in err and "search" in err


def test_search_apostrophe_keyword_exit_1(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "O'Brien", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert json.loads(out) == []
