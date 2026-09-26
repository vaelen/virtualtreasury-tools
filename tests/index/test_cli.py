# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import io
import json
import shutil
from pathlib import Path

from rich.console import Console
from rich.text import Text

from vtextract.index.cli import (
    THEMES,
    _build_results_table,
    _build_volumes_table,
    _highlight_title,
    main,
)
from vtextract.index.models import SearchResult, VolumeInfo

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
    # estimated_date keys are always present in JSON output for shape stability.
    assert "estimated_date" in payload[0]
    assert "estimated_source" in payload[0]


def test_json_matched_pages_include_file_paths(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["search", "memorial", "--in", "transcription",
                 "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    pages = payload[0]["matched_pages"]
    assert pages, "expected a transcription match to carry matched_pages"
    pg = next(p for p in pages if p["page_key"] == "volA_p1.jpg")
    assert pg["root_id"] == "volA"
    page_dir = archive / "pages" / "volA"
    # the .txt exists in the fixture -> full path; image/metadata absent -> null
    assert pg["transcription"] == str((page_dir / "volA_p1.jpg.txt").resolve())
    assert pg["image"] is None
    assert pg["metadata"] is None


def test_search_limit_zero_returns_all(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    capped = main(["search", "--archive", str(archive), "--limit", "1", "--json"])
    capped_out = json.loads(capsys.readouterr().out)
    unlimited = main(["search", "--archive", str(archive), "--limit", "0", "--json"])
    unlimited_out = json.loads(capsys.readouterr().out)
    assert capped == 0 and unlimited == 0
    assert len(capped_out) == 1
    assert [r["isadg_id"] for r in unlimited_out] == [300, 100, 200]


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
    for header in ("ID", "Date", "Est.", "Reference", "Title"):
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
    title_cell = list(table.columns[4].cells)[0]
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


def test_page_json_mid_volume_has_prev_and_next(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/volA_p1.jpg", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["current"]["page_key"] == "volA_p1.jpg"
    assert payload["current"]["ordinal"] == 2
    assert payload["previous"]["page_key"] == "volA_p0.jpg"
    assert payload["next"] is None  # volA_p1 is the last page
    assert payload["volume"]["title"] == "Registry of Deeds Transcript Book 86: memorials 1737"
    assert payload["current"]["transcription"].endswith("volA_p1.jpg.txt")


def test_page_json_first_page_has_no_previous(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/volA_p0.jpg", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["previous"] is None
    assert payload["next"]["page_key"] == "volA_p1.jpg"


def test_page_not_found_exit_1(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/nope.jpg", "--archive", str(archive), "--json"])
    out = capsys.readouterr().out
    assert code == 1
    assert json.loads(out) is None


def test_page_not_found_plain_exit_1(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/nope.jpg", "--archive", str(archive)])
    out = capsys.readouterr().out
    assert code == 1
    assert "page not found" in out


def test_page_bad_ref_exit_2(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "no-slash-here", "--archive", str(archive)])
    err = capsys.readouterr().err
    assert code == 2
    assert "root_id" in err


def test_page_without_ordinal_warns_exit_0(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    from vtextract.index.builder import INDEX_RELPATH
    import sqlite3
    conn = sqlite3.connect(archive / INDEX_RELPATH)
    conn.execute("UPDATE page SET ordinal=NULL WHERE root_id='volA' AND page_key='volA_p1.jpg'")
    conn.commit()
    conn.close()
    code = main(["page", "volA/volA_p1.jpg", "--archive", str(archive), "--json"])
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert code == 0
    assert payload["current"]["page_key"] == "volA_p1.jpg"
    assert payload["previous"] is None and payload["next"] is None
    assert "ordering" in out.err.lower()


def test_volumes_json_includes_title(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    main(["volumes", "--archive", str(archive), "--json"])
    payload = json.loads(capsys.readouterr().out)
    volA = next(v for v in payload if v["root_id"] == "volA")
    assert volA["title"] == "Registry of Deeds Transcript Book 86: memorials 1737"


def test_page_table_output_shows_paths(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "volA/volA_p1.jpg", "--archive", str(archive)])
    out = capsys.readouterr().out
    assert code == 0
    assert "volA_p0.jpg" in out and "volA_p1.jpg" in out


def test_page_no_ref_prints_help_exit_2(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["page", "--archive", str(archive)])
    err = capsys.readouterr().err
    assert code == 2
    assert "usage: vtindex page" in err
    assert "root_id" in err


def _sample_volume(root_id: str = "volA") -> VolumeInfo:
    return VolumeInfo(
        root_id=root_id, label="Book 86", reference_code="FIX 1/A",
        item_count=2, title="Registry of Deeds Transcript Book 86",
    )


def test_volumes_table_prints_header(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    capsys.readouterr()
    code = main(["volumes", "--archive", str(archive)])
    out = capsys.readouterr().out
    assert code == 0
    for header in ("Root ID", "Items", "Title", "Reference"):
        assert header in out
    assert "volA" in out


def test_volumes_bw_theme_has_no_zebra_striping():
    table = _build_volumes_table([_sample_volume()], theme=THEMES["bw"])
    assert table.row_styles == []


def test_volumes_dark_theme_renders_ansi_color():
    table = _build_volumes_table([_sample_volume()], theme=THEMES["dark"])
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, width=120, color_system="standard").print(table)
    assert "\x1b[" in buf.getvalue()


def test_volumes_theme_flags_accepted(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    for flag in ("--dark", "--light", "--bw", "--plain"):
        capsys.readouterr()
        code = main(["volumes", flag, "--archive", str(archive)])
        assert code == 0
        assert "volA" in capsys.readouterr().out


def test_page_theme_flags_accepted(tmp_path, capsys):
    archive = _archive(tmp_path)
    main(["build", "--archive", str(archive)])
    for flag in ("--dark", "--light", "--bw", "--plain"):
        capsys.readouterr()
        code = main(["page", "volA/volA_p1.jpg", flag, "--archive", str(archive)])
        assert code == 0
        assert "volA_p1.jpg" in capsys.readouterr().out


def _build_people_archive(tmp_path):
    from vtextract.index.builder import build
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "a.jpg.names.json").write_text(
        '{"schema":2,"model":"m","people":[["William Young","Wm Young"]]}'
    )
    build(tmp_path)
    return tmp_path


def test_cli_people_json(tmp_path, capsys):
    from vtextract.index.cli import main
    archive = _build_people_archive(tmp_path)
    rc = main(["people", "Young", "--archive", str(archive), "--json"])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out[0]["canonical"] == "William Young"


def test_cli_people_no_match(tmp_path, capsys):
    from vtextract.index.cli import main
    archive = _build_people_archive(tmp_path)
    rc = main(["people", "Nobody", "--archive", str(archive), "--json"])
    assert rc == 1


