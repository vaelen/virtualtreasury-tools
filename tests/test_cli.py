# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
from pathlib import Path

import pytest
import httpx

from vtextract import cli


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


# --- run() wiring --------------------------------------------------------

def test_run_errors_when_no_criteria(tmp_path):
    with pytest.raises(SystemExit):
        cli.run(["--out", str(tmp_path)], env={"VT_AUTH": "x", "VT_DELAY": "0"})


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
        ["--title", "--all", "houston", "--out", str(tmp_path), "--context-pages", "0"],
        env={"VT_AUTH": "x", "VT_DELAY": "0"},
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


def test_run_returns_nonzero_when_a_resource_fails(tmp_path, monkeypatch):
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
        ["houston", "--out", str(tmp_path), "--context-pages", "0"],
        env={"VT_AUTH": "x", "VT_DELAY": "0", "VT_MAX_RETRIES": "0"},
    )
    assert exit_code == 1


def test_run_twice_skips_completed_resource(tmp_path, monkeypatch):
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

    argv = ["houston", "--out", str(tmp_path), "--context-pages", "0"]
    env = {"VT_AUTH": "x", "VT_DELAY": "0"}

    assert cli.run(argv, env=env) == 0
    assert counts["item"] == 1
    assert counts["loris"] == 1

    counts["item"] = 0
    counts["loris"] = 0
    assert cli.run(argv, env=env) == 0
    assert counts["item"] == 0
    assert counts["loris"] == 0
