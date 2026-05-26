# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest
import httpx

from vtextract import cli


def test_page_size_rejects_zero():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["https://virtualtreasury.ie/search-results?kwList=x",
             "--out", "out", "--page-size", "0"]
        )


def test_context_pages_rejects_negative():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["https://virtualtreasury.ie/search-results?kwList=x",
             "--out", "out", "--context-pages", "-1"]
        )


def test_run_archives_results_end_to_end(tmp_path, monkeypatch):
    # Stub the network: one search page with one result, then the item fan-out.
    search_response = {
        "generalInfo": {"totalDocs": 1, "docNumberPerPage": 100, "currentPage": 1},
        "resultInfoList": [
            {"isadgID": 474234, "displayReferenceCode": "IMC 1954/RoD/1/1737/550",
             "displayTitle": "Will of MITCHELL, CALEB"}
        ],
    }

    from pathlib import Path
    examples = Path(__file__).resolve().parent.parent / "docs" / "examples"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/IR_REST_V2/webapi/doc_search":
            return httpx.Response(200, json=search_response)
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=(examples / "item" / "isadg-identity-statements" / "response.json").read_bytes())
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=(examples / "item" / "manifest" / "response.json").read_bytes())
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=(examples / "item" / "list" / "response.json").read_bytes())
        if path.startswith("/loris/"):
            return httpx.Response(200, content=(examples / "item" / "loris" / "response.jpg").read_bytes())
        return httpx.Response(404, text=path)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))

    exit_code = cli.run(
        ["https://virtualtreasury.ie/search-results?kwList=houston",
         "--out", str(tmp_path), "--context-pages", "0"],
        env={"VT_AUTH": "x", "VT_DELAY": "0"},
    )
    assert exit_code == 0
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
        path = request.url.path
        if path == "/IR_REST_V2/webapi/doc_search":
            return httpx.Response(200, json=search_response)
        # Detail call 404s -> fetch_resource raises -> run records a failure.
        return httpx.Response(404, text=path)

    monkeypatch.setattr(cli, "_make_transport", lambda: httpx.MockTransport(handler))

    exit_code = cli.run(
        ["https://virtualtreasury.ie/search-results?kwList=houston",
         "--out", str(tmp_path), "--context-pages", "0"],
        env={"VT_AUTH": "x", "VT_DELAY": "0", "VT_MAX_RETRIES": "0"},
    )
    assert exit_code == 1
