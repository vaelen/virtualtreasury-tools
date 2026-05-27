# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
from pathlib import Path

import pytest
import httpx

from vtextract import cli
from vtextract.config import load_config, write_config


def _write_config(tmp_path, token="x", delay=0, max_retries=3):
    """A config file with credentials and zero delay for fast offline tests."""
    path = tmp_path / "vt.toml"
    write_config(
        path,
        {"extract": {"auth": {"token": token},
                     "http": {"delay": delay, "max_retries": max_retries}}},
    )
    return path


# --- argument validation -------------------------------------------------

def test_page_size_rejects_zero():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--out", "out", "--page-size", "0"])


def test_context_pages_rejects_negative():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--out", "out", "--context-pages", "-1"])


# --- the criteria walker -------------------------------------------------

def _split(argv):
    return cli.split_and_group(argv, cli.build_parser())


def test_walker_groups_interleaved_flags_and_keywords():
    globals_, criteria = _split(
        ["--title", "--all", "memorial", "houston",
         "--transcription", "--any", "castle", "watchmaker",
         "--place", "--exact", "Dublin", "--out", "./archive"]
    )
    assert globals_ == ["--out", "./archive"]
    assert [(f.field, f.operand, f.keywords) for f in criteria.filters] == [
        ("title", "ALL", ["memorial", "houston"]),
        ("kwTranscription", "ANY", ["castle", "watchmaker"]),
        ("kg_label", "EXACT", ["Dublin"]),
    ]
    assert criteria.boost == "Place"


def test_walker_defaults_field_to_all_and_operand_to_all():
    _, criteria = _split(["houston"])
    assert [(f.field, f.operand, f.keywords) for f in criteria.filters] == [
        ("all", "ALL", ["houston"]),
    ]


def test_walker_resets_operand_on_new_field():
    _, criteria = _split(["--title", "--any", "a", "--transcription", "b"])
    assert criteria.filters[0].operand == "ANY"
    assert criteria.filters[1].operand == "ALL"  # reset by the new field flag


def test_walker_skips_empty_group_between_consecutive_field_flags():
    _, criteria = _split(["--title", "--creator", "x"])
    assert [(f.field, f.keywords) for f in criteria.filters] == [("creator", ["x"])]


def test_walker_operand_before_any_field_uses_default_field():
    _, criteria = _split(["--any", "cat", "dog"])
    assert [(f.field, f.operand, f.keywords) for f in criteria.filters] == [
        ("all", "ANY", ["cat", "dog"]),
    ]


def test_walker_person_then_place_boost_last_wins():
    _, criteria = _split(["--person", "Joyce", "--place", "Dublin"])
    assert [f.field for f in criteria.filters] == ["kg_label", "kg_label"]
    assert criteria.boost == "Place"


def test_walker_sort_flags_map_to_resulting_sorting():
    assert cli.build_parser().parse_args(["--out", "o", "--newest"]).sorting == "descending"
    assert cli.build_parser().parse_args(["--out", "o", "--oldest"]).sorting == "ascending"
    assert cli.build_parser().parse_args(["--out", "o"]).sorting == "relevance"


def test_walker_rejects_unknown_option():
    with pytest.raises(SystemExit):
        _split(["--bogus", "x"])


# --- progress reporting --------------------------------------------------

class _SpyReporter:
    """Records the Reporter calls _extract makes, as a context manager."""

    def __init__(self):
        self.calls = []

    def __enter__(self):
        self.calls.append("enter")
        return self

    def __exit__(self, *exc):
        self.calls.append("exit")
        return False

    def start_item(self, label):
        self.calls.append(("start_item", label))

    def item_pages(self, n):
        self.calls.append(("item_pages", n))

    def page_done(self):
        self.calls.append("page_done")

    def item_done(self, label):
        self.calls.append(("item_done", label))

    def skip(self, label):
        self.calls.append(("skip", label))

    def fail(self, label, exc):
        self.calls.append(("fail", label))

    def finish(self, completed, failed):
        self.calls.append(("finish", completed, failed))

    def verify_summary(self, counts, flagged):
        self.calls.append(("verify_summary", counts, flagged))


def test_extract_drives_reporter_for_skip_and_fetch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    archive.mark_resource_complete(100, pages=[], search_id="x")  # already done

    monkeypatch.setattr(
        cli, "fetch_resource",
        lambda *a, **k: SimpleNamespace(isadg_id=200),
    )
    client = SimpleNamespace(close=lambda: None)
    reporter = _SpyReporter()

    completed, failed = cli._extract(
        client, archive, [{"isadgID": 100}, {"isadgID": 200}],
        search_id="x", context_pages=0, reporter=reporter,
    )

    assert (completed, failed) == (1, 0)
    assert ("skip", 100) in reporter.calls
    assert ("start_item", 200) in reporter.calls
    assert ("item_done", 200) in reporter.calls
    assert reporter.calls[0] == "enter"
    assert reporter.calls.index("exit") < reporter.calls.index(("finish", 1, 0))


def test_extract_emits_verify_summary_when_refresh(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    # Mark one resource complete so we can also exercise the refresh-skips-nothing path.
    archive.mark_resource_complete(100, pages=[], search_id="x")

    monkeypatch.setattr(
        cli, "fetch_resource",
        lambda *a, **k: SimpleNamespace(isadg_id=100),
    )
    client = SimpleNamespace(close=lambda: None)
    reporter = _SpyReporter()

    completed, failed = cli._extract(
        client, archive, [{"isadgID": 100}],
        search_id="x", context_pages=0, reporter=reporter,
        refresh=True,
    )

    assert (completed, failed) == (1, 0)
    # verify_summary must appear in the calls list when refresh=True
    vs_calls = [c for c in reporter.calls if isinstance(c, tuple) and c[0] == "verify_summary"]
    assert len(vs_calls) == 1
    _, counts, flagged = vs_calls[0]
    assert isinstance(counts, dict)
    assert isinstance(flagged, list)
    # verify_summary must come before finish
    assert reporter.calls.index(vs_calls[0]) < reporter.calls.index(("finish", 1, 0))


def test_extract_omits_verify_summary_without_refresh(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from vtextract.archive import Archive

    archive = Archive(tmp_path)

    monkeypatch.setattr(
        cli, "fetch_resource",
        lambda *a, **k: SimpleNamespace(isadg_id=200),
    )
    client = SimpleNamespace(close=lambda: None)
    reporter = _SpyReporter()

    cli._extract(
        client, archive, [{"isadgID": 200}],
        search_id="x", context_pages=0, reporter=reporter,
        # refresh defaults to False
    )

    vs_calls = [c for c in reporter.calls if isinstance(c, tuple) and c[0] == "verify_summary"]
    assert vs_calls == []


# --- dispatch ------------------------------------------------------------

def test_no_subcommand_prints_help_and_exits_nonzero(capsys):
    code = cli.run([])
    assert code != 0
    assert "search" in capsys.readouterr().err


def test_unknown_subcommand_exits_nonzero(capsys):
    code = cli.run(["bogus"])
    assert code != 0


# --- auth command --------------------------------------------------------

def test_auth_stores_token_verbatim(tmp_path, monkeypatch):
    path = tmp_path / "vt.toml"
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "cGFzdGVk")
    code = cli.run(["auth", "--config", str(path)])
    assert code == 0
    assert load_config(path).auth_header == "Basic cGFzdGVk"


def test_auth_with_username_stores_computed_digest(tmp_path, monkeypatch):
    import base64
    path = tmp_path / "vt.toml"
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "secret")
    code = cli.run(["auth", "user", "--config", str(path)])
    assert code == 0
    expected = base64.b64encode(b"user:secret").decode()
    assert load_config(path).auth_header == f"Basic {expected}"


# --- search command: run() wiring ----------------------------------------

def test_search_errors_when_no_criteria(tmp_path):
    config = _write_config(tmp_path)
    with pytest.raises(SystemExit):
        cli.run(["search", "--out", str(tmp_path), "--config", str(config)])


def test_search_without_credentials_reports_guidance(tmp_path, capsys):
    config = tmp_path / "vt.toml"  # no file written -> no token
    code = cli.run(["search", "houston", "--out", str(tmp_path), "--config", str(config)])
    assert code != 0
    assert "vtextract auth" in capsys.readouterr().err


EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def _item_handler(request, search_response, posted=None):
    path = request.url.path
    if path == "/IR_REST_V2/webapi/doc_search":
        if posted is not None:
            posted.append(json.loads(request.content))
        return httpx.Response(200, json=search_response)
    if path == "/rest/isadg-identity-statements/474234":
        return httpx.Response(200, content=(EXAMPLES / "item" / "isadg-identity-statements" / "response.json").read_bytes())
    if path == "/iiif/v1/474234/manifest":
        return httpx.Response(200, content=(EXAMPLES / "item" / "manifest" / "response.json").read_bytes())
    if path == "/iiif/v1/208925/list/197350":
        return httpx.Response(200, content=(EXAMPLES / "item" / "list" / "response.json").read_bytes())
    if path.startswith("/loris/"):
        return httpx.Response(200, content=(EXAMPLES / "item" / "loris" / "response.jpg").read_bytes())
    return httpx.Response(404, text=path)


def test_run_archives_results_from_criteria_flags(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "IMC 1954/RoD/1/1737/550",
             "displayTitle": "Will of MITCHELL, CALEB"}
        ],
    }
    posted = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _item_handler(r, search_response, posted)),
    )

    exit_code = cli.run(
        ["search", "--title", "--all", "houston", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config)],
    )
    assert exit_code == 0
    # The criteria flags reached the POST body as parallel arrays + scaffolding.
    body = posted[0]
    assert body["indexDBName"] == "beyond_2022"
    assert body["kwList"] == ["houston"]
    assert body["kwOperList"] == ["ALL"]
    assert body["kwSearchFieldList"] == ["title"]
    assert body["searchDocumentRepositoryNameList"] == []
    assert body["resultSorting"] == "relevance"
    assert (tmp_path / "items" / "474234" / "metadata.json").exists()
    assert (tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg").exists()


def test_search_defaults_archive_to_config_when_out_omitted(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    path = tmp_path / "vt.toml"
    write_config(
        path,
        {"archive": str(archive),
         "extract": {"auth": {"token": "x"}, "http": {"delay": 0}}},
    )
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}
        ],
    }
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _item_handler(r, search_response)),
    )

    exit_code = cli.run(["search", "houston", "--context-pages", "0", "--config", str(path)])
    assert exit_code == 0
    assert (archive / "items" / "474234" / "metadata.json").exists()


def test_run_returns_nonzero_when_a_resource_fails(tmp_path, monkeypatch):
    config = _write_config(tmp_path, max_retries=0)
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/IR_REST_V2/webapi/doc_search":
            return httpx.Response(200, json=search_response)
        return httpx.Response(404, text=request.url.path)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))

    exit_code = cli.run(
        ["search", "houston", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config)],
    )
    assert exit_code == 1


# --- get command ---------------------------------------------------------


def _get_handler(request, *, item_calls=None, refcode_calls=None):
    """Item handler for `get`, with a reference-code resolution branch."""
    path = request.url.path
    if path == "/rest/isadg-identity-statements/" and request.url.params.get("isadgReferenceCode"):
        if refcode_calls is not None:
            refcode_calls.append(request.url.params["isadgReferenceCode"])
        return httpx.Response(200, content=(EXAMPLES / "item" / "isadg-identity-statements" / "response.json").read_bytes())
    if path == "/rest/isadg-identity-statements/474234":
        if item_calls is not None:
            item_calls.append(path)
        return httpx.Response(200, content=(EXAMPLES / "item" / "isadg-identity-statements" / "response.json").read_bytes())
    if path == "/iiif/v1/474234/manifest":
        return httpx.Response(200, content=(EXAMPLES / "item" / "manifest" / "response.json").read_bytes())
    if path == "/iiif/v1/208925/list/197350":
        return httpx.Response(200, content=(EXAMPLES / "item" / "list" / "response.json").read_bytes())
    if path.startswith("/loris/"):
        return httpx.Response(200, content=(EXAMPLES / "item" / "loris" / "response.jpg").read_bytes())
    return httpx.Response(404, text=path)


def test_get_without_credentials_reports_guidance(tmp_path, capsys):
    config = tmp_path / "vt.toml"  # no file written -> no token
    code = cli.run(["get", "474234", "--out", str(tmp_path), "--config", str(config)])
    assert code != 0
    assert "vtextract auth" in capsys.readouterr().err


def test_get_numeric_id_archives_resource_with_metadata_from_detail(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setattr(
        cli, "_make_transport", lambda: httpx.MockTransport(lambda r: _get_handler(r))
    )
    exit_code = cli.run(
        ["get", "474234", "--out", str(tmp_path), "--context-pages", "0", "--config", str(config)]
    )
    assert exit_code == 0
    metadata = json.loads((tmp_path / "items" / "474234" / "metadata.json").read_text())
    # the bare numeric hit carries no display fields; they come from the detail
    assert metadata["referenceCode"] == "IMC 1954/RoD/1/1737/550"
    assert metadata["title"].startswith("Will of MITCHELL, CALEB")


def test_get_reference_code_resolves_then_archives(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    refcode_calls: list[str] = []
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(
            lambda r: _get_handler(r, item_calls=item_calls, refcode_calls=refcode_calls)
        ),
    )
    exit_code = cli.run(
        ["get", "IMC 1954/RoD/1/1737/550", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config)]
    )
    assert exit_code == 0
    assert refcode_calls == ["IMC-1954-RoD-1-1737-550"]  # the single detail fetch
    assert item_calls == []  # no redundant by-id GET
    assert (tmp_path / "items" / "474234" / "metadata.json").exists()


def test_get_one_bad_identifier_does_not_abort_run(tmp_path, monkeypatch):
    config = _write_config(tmp_path, max_retries=0)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/isadg-identity-statements/" and request.url.params.get("isadgReferenceCode") == "BAD-CODE":
            return httpx.Response(404, text="no such reference code")
        return _get_handler(request)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))
    exit_code = cli.run(
        ["get", "BAD CODE", "474234", "--out", str(tmp_path),
         "--context-pages", "0", "--config", str(config)]
    )
    assert exit_code == 1  # the bad reference code is counted as a failure
    assert (tmp_path / "items" / "474234" / "metadata.json").exists()  # valid id still archived


def _refresh_get_handler(request, *, item_calls=None, loris=None):
    """Like _get_handler, plus a HEAD branch for /loris/ image verification."""
    path = request.url.path
    if path.startswith("/loris/") and request.method == "HEAD":
        img = (EXAMPLES / "item" / "loris" / "response.jpg").read_bytes()
        return httpx.Response(200, headers={"content-length": str(len(img))})
    if path.startswith("/loris/") and loris is not None:
        loris.append(path)
    if path == "/rest/isadg-identity-statements/474234" and item_calls is not None:
        item_calls.append(path)
    return _get_handler(request)


def test_get_refresh_reprocesses_completed_resource(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, item_calls=item_calls)),
    )
    # --context-pages 0: these tests don't mock the volume manifest, so no context fetch.
    base = ["get", "474234", "--out", str(tmp_path), "--config", str(config),
            "--context-pages", "0"]
    assert cli.run(base) == 0
    item_calls.clear()
    # without --refresh it would be skipped; with --refresh the detail is re-fetched
    assert cli.run(base + ["--refresh"]) == 0
    assert item_calls == ["/rest/isadg-identity-statements/474234"]


def test_get_refresh_verifies_image_with_head_not_get(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    loris: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, loris=loris)),
    )
    base = ["get", "474234", "--out", str(tmp_path), "--config", str(config),
            "--context-pages", "0"]
    assert cli.run(base) == 0
    loris.clear()  # GET-only list (HEAD requests are not appended)
    assert cli.run(base + ["--refresh"]) == 0
    assert loris == []  # size matched on HEAD -> no image GET


def test_search_refresh_parses_as_global_flag():
    from vtextract.cli import build_parser, split_and_group
    globals_, criteria = split_and_group(["houston", "--refresh"], build_parser())
    assert "--refresh" in globals_
    assert build_parser().parse_args(globals_).refresh is True
    assert [f.keywords for f in criteria.filters] == [["houston"]]


def test_get_twice_skips_completed_resource(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _get_handler(r, item_calls=item_calls)),
    )
    argv = ["get", "474234", "--out", str(tmp_path), "--context-pages", "0", "--config", str(config)]
    assert cli.run(argv) == 0
    assert item_calls == ["/rest/isadg-identity-statements/474234"]
    item_calls.clear()
    assert cli.run(argv) == 0
    assert item_calls == []  # already complete -> no re-fetch


# --- refresh command ---------------------------------------------------------


def _seed_one_item(tmp_path, monkeypatch):
    """Archive item 474234 so the refresh command has something to enumerate."""
    config = _write_config(tmp_path)
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _get_handler(r)),
    )
    assert cli.run(["get", "474234", "--out", str(tmp_path), "--config", str(config),
                    "--context-pages", "0"]) == 0
    return config


def test_refresh_with_yes_reprocesses_all_items(tmp_path, monkeypatch):
    config = _seed_one_item(tmp_path, monkeypatch)
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, item_calls=item_calls)),
    )
    code = cli.run(["refresh", "--yes", "--out", str(tmp_path), "--config", str(config),
                    "--context-pages", "0"])
    assert code == 0
    assert item_calls == ["/rest/isadg-identity-statements/474234"]  # re-fetched


def test_refresh_declined_at_prompt_does_nothing(tmp_path, monkeypatch):
    config = _seed_one_item(tmp_path, monkeypatch)
    item_calls: list[str] = []
    monkeypatch.setattr(
        cli, "_make_transport",
        lambda: httpx.MockTransport(lambda r: _refresh_get_handler(r, item_calls=item_calls)),
    )
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli, "_prompt_yes_no", lambda *_a, **_k: False)
    code = cli.run(["refresh", "--out", str(tmp_path), "--config", str(config)])
    assert code == 0
    assert item_calls == []  # declined -> no requests


def test_refresh_non_tty_without_yes_aborts(tmp_path, monkeypatch, capsys):
    config = _seed_one_item(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
    code = cli.run(["refresh", "--out", str(tmp_path), "--config", str(config)])
    assert code == 2
    assert "--yes" in capsys.readouterr().err


def test_refresh_empty_archive_reports_and_exits_zero(tmp_path, monkeypatch, capsys):
    config = _write_config(tmp_path)
    (tmp_path / "items").mkdir()  # archive dir exists but has no items
    code = cli.run(["refresh", "--yes", "--out", str(tmp_path), "--config", str(config)])
    assert code == 0
    assert "no items" in capsys.readouterr().err.lower()


def test_refresh_fresh_archive_without_items_dir_exits_zero(tmp_path, capsys):
    # A brand-new archive has no items/ directory at all; refresh must not crash.
    config = _write_config(tmp_path)
    out = tmp_path / "fresh"
    code = cli.run(["refresh", "--yes", "--out", str(out), "--config", str(config)])
    assert code == 0
    assert "no items" in capsys.readouterr().err.lower()
    assert not (out / "items").exists()  # refresh did not need to create it


def test_run_twice_skips_completed_resource(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}
        ],
    }
    counts = {"item": 0, "loris": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/IR_REST_V2/webapi/doc_search":
            return httpx.Response(200, json=search_response)
        if path == "/rest/isadg-identity-statements/474234":
            counts["item"] += 1
            return httpx.Response(200, content=(EXAMPLES / "item" / "isadg-identity-statements" / "response.json").read_bytes())
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=(EXAMPLES / "item" / "manifest" / "response.json").read_bytes())
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=(EXAMPLES / "item" / "list" / "response.json").read_bytes())
        if path.startswith("/loris/"):
            counts["loris"] += 1
            return httpx.Response(200, content=(EXAMPLES / "item" / "loris" / "response.jpg").read_bytes())
        return httpx.Response(404, text=path)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))

    argv = ["search", "houston", "--out", str(tmp_path),
            "--context-pages", "0", "--config", str(config)]

    assert cli.run(argv) == 0
    assert counts["item"] == 1
    assert counts["loris"] == 1

    counts["item"] = 0
    counts["loris"] = 0
    assert cli.run(argv) == 0
    assert counts["item"] == 0
    assert counts["loris"] == 0
