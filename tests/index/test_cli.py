# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import io
import json
import shutil
from pathlib import Path

from rich.console import Console
from rich.text import Text

from vtextract.index.cli import THEMES, _build_results_table, _highlight_title, main
from vtextract.index.models import SearchResult

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def _sample_result(title: str = "Will of HOUSTON, JOHN") -> SearchResult:
    return SearchResult(
        isadg_id=100, title=title, reference_code="FIX 1/A/1", repository=None,
        content_date="1737-05-06", created_date=None, matched_fields=["title"],
        matched_pages=[], score=0.0, path="items/100",
    )


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


def test_search_table_prints_header(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "Houston", "--in", "title", "--archive", str(archive)])
    out = capsys.readouterr().out
    assert code == 0
    for header in ("ID", "Date", "Reference", "Title"):
        assert header in out
    assert "Fields" not in out
    assert "100" in out
    assert "HOUSTON" in out


def test_highlight_title_marks_matching_words():
    t = _highlight_title("Will of HOUSTON, JOHN", "houston john", "bold yellow")
    spans = sorted((s.start, s.end) for s in t.spans)
    assert (8, 15) in spans   # HOUSTON
    assert (17, 21) in spans  # JOHN


def test_highlight_title_no_query_has_no_spans():
    assert _highlight_title("Will of HOUSTON", None, "bold yellow").spans == []


def test_highlight_title_empty_style_has_no_spans():
    # the --plain theme carries no match style, so nothing is highlighted
    assert _highlight_title("Will of HOUSTON", "houston", THEMES["plain"].match_style).spans == []


def test_themes_cover_all_four_modes():
    assert set(THEMES) == {"dark", "light", "bw", "plain"}


def test_bw_theme_has_no_zebra_striping():
    table = _build_results_table([_sample_result()], theme=THEMES["bw"], query=None)
    assert table.row_styles == []


def test_dark_theme_renders_ansi_color():
    table = _build_results_table([_sample_result()], theme=THEMES["dark"], query="houston")
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, width=120, color_system="standard").print(table)
    assert "\x1b[" in buf.getvalue()


def test_title_cell_is_highlighted_text():
    table = _build_results_table([_sample_result()], theme=THEMES["dark"], query="houston")
    title_cell = list(table.columns[3].cells)[0]
    assert isinstance(title_cell, Text)
    assert title_cell.spans  # HOUSTON highlighted


def test_search_theme_flags_accepted(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    for flag in ("--dark", "--light", "--bw", "--plain"):
        capsys.readouterr()
        code = main(["search", "Houston", "--in", "title", flag, "--archive", str(archive)])
        assert code == 0
        assert "HOUSTON" in capsys.readouterr().out


def test_search_theme_flags_mutually_exclusive(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    try:
        main(["search", "Houston", "--dark", "--light", "--archive", str(archive)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected mutually-exclusive flags to error")


def test_search_apostrophe_keyword_exit_1(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "O'Brien", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert json.loads(out) == []
