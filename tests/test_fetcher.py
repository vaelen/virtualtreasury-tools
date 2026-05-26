# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
from pathlib import Path

import httpx

from vtextract.client import Client
from vtextract.fetcher import fetch_resource

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def _item_json(call: str) -> bytes:
    return (EXAMPLES / "item" / call / "response.json").read_bytes()


def _item_image() -> bytes:
    return (EXAMPLES / "item" / "loris" / "response.jpg").read_bytes()


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/rest/isadg-identity-statements/474234":
        return httpx.Response(200, content=_item_json("isadg-identity-statements"))
    if path == "/iiif/v1/474234/manifest":
        return httpx.Response(200, content=_item_json("manifest"))
    if path == "/iiif/v1/208925/list/197350":
        return httpx.Response(200, content=_item_json("list"))
    if path == "/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg":
        return httpx.Response(200, content=_item_image())
    return httpx.Response(404, text=f"unexpected {path}")


def _client() -> Client:
    return Client(
        base_url="https://by2022-prod.adaptcentre.ie",
        auth_header="Basic x",
        user_agent="UA",
        transport=httpx.MockTransport(_handler),
        delay=0.0,
        sleep_func=lambda _s: None,
    )


def test_fetch_resource_downloads_page_metadata_and_transcription(tmp_path):
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    search_hit = {
        "isadgID": 474234,
        "displayReferenceCode": "IMC 1954/RoD/1/1737/550",
        "displayTitle": "Will of MITCHELL, CALEB",
    }
    record = fetch_resource(
        _client(), archive, search_hit, search_id="houston", context_pages=0
    )

    metadata = json.loads((tmp_path / "items" / "474234" / "metadata.json").read_text())
    assert metadata["referenceCode"] == "IMC 1954/RoD/1/1737/550"
    assert len(metadata["pages"]) == 1
    assert metadata["pages"][0]["role"] == "primary"
    assert metadata["pages"][0]["path"] == "pages/208925/IMC_1954_RoD_1_Page_253.jpg"

    page_dir = tmp_path / "pages" / "208925"
    assert (page_dir / "IMC_1954_RoD_1_Page_253.jpg").exists()
    assert "REGISTRY OF DEEDS, DUBLIN" in (page_dir / "IMC_1954_RoD_1_Page_253.jpg.txt").read_text()
    assert archive.is_resource_complete(474234) is True
    assert record.isadg_id == 474234


def test_fetch_resource_skips_already_stored_page(tmp_path):
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    search_hit = {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}

    calls = {"loris": 0}
    base_handler = _handler

    def counting_handler(request: httpx.Request) -> httpx.Response:
        if "/loris/" in request.url.path:
            calls["loris"] += 1
        return base_handler(request)

    def client():
        return Client(
            base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
            user_agent="UA", transport=httpx.MockTransport(counting_handler),
            delay=0.0, sleep_func=lambda _s: None,
        )

    fetch_resource(client(), archive, search_hit, search_id="s1", context_pages=0)
    fetch_resource(client(), archive, dict(search_hit, isadgID=474234), search_id="s2", context_pages=0)
    assert calls["loris"] == 1


def test_fetch_resource_pulls_context_pages_and_writes_volume_info(tmp_path):
    from vtextract.archive import Archive

    # Root manifest with three pages; the item's page is the middle one (p235288).
    root_manifest = {
        "label": "Registry of Deeds... abstracts of wills, volume 1: 1708-45",
        "metadata": [{"label": "ReferenceCode", "value": "IMC 1954/RoD/1"}],
        "sequences": [{"canvases": [
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/before",
             "label": "before", "width": 1, "height": 1,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/before.jpg/full/full/0/default.jpg"}}],
             "otherContent": []},
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288",
             "label": "IMC 1954/RoD/1/1737/550", "width": 826, "height": 1368,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg"}}],
             "otherContent": [{"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"}]},
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/after",
             "label": "after", "width": 1, "height": 1,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/after.jpg/full/full/0/default.jpg"}}],
             "otherContent": []},
        ]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/iiif/v1/208925/manifest":
            return httpx.Response(200, json=root_manifest)
        if path.startswith("/loris/"):
            return httpx.Response(200, content=b"\xff\xd8img")
        return _handler(request)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    search_hit = {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}

    record = fetch_resource(client, archive, search_hit, search_id="s", context_pages=1)

    roles = {r.page_key: r.role for r in record.pages}
    assert roles["IMC_1954_RoD_1_Page_253.jpg"] == "primary"
    assert roles["before.jpg"] == "context"
    assert roles["after.jpg"] == "context"
    assert (tmp_path / "pages" / "208925" / "before.jpg").exists()
    assert (tmp_path / "pages" / "208925" / "after.jpg").exists()
    import json as _json
    vol = _json.loads((tmp_path / "pages" / "208925" / "volume.json").read_text())
    assert vol["reference_code"] == "IMC 1954/RoD/1"


def test_fetch_resource_empty_manifest_completes_with_no_pages(tmp_path):
    from vtextract.archive import Archive

    empty_manifest = {"sequences": [{"canvases": []}]}
    calls = {"loris": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, json=empty_manifest)
        if "/loris/" in path:
            calls["loris"] += 1
            return httpx.Response(200, content=b"\xff\xd8img")
        return httpx.Response(404, text=path)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    search_hit = {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"}

    record = fetch_resource(client, archive, search_hit, search_id="s", context_pages=1)

    assert record.pages == []
    assert calls["loris"] == 0
    assert archive.is_resource_complete(474234) is True
