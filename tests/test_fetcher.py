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
        _client(), archive, search_hit, search_id="houston", context_pages=0, images=True
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


def test_fetch_resource_reports_page_progress(tmp_path):
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    search_hit = {"isadgID": 474234}
    started: list[int] = []
    pages = {"n": 0}

    fetch_resource(
        _client(), archive, search_hit,
        search_id="houston", context_pages=0, images=True,
        on_item_start=started.append,
        on_page=lambda: pages.__setitem__("n", pages["n"] + 1),
    )

    assert started == [1]  # one primary page, no context
    assert pages["n"] == 1  # on_page fired once per page processed


def test_fetch_resource_by_reference_code_uses_query_not_id_lookup(tmp_path):
    from vtextract.archive import Archive

    calls = {"refcode": [], "by_id": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/isadg-identity-statements/" and request.url.params.get("isadgReferenceCode"):
            calls["refcode"].append(request.url.params["isadgReferenceCode"])
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/rest/isadg-identity-statements/474234":
            calls["by_id"] += 1  # must NOT happen on the reference-code path
        return _handler(request)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    # The hit carries only the reference code (spaces/slashes normalised on fetch).
    record = fetch_resource(
        client, archive, {"displayReferenceCode": "IMC 1954/RoD/1/1737/550"},
        search_id="get", context_pages=0,
    )

    assert calls["refcode"] == ["IMC-1954-RoD-1-1737-550"]  # one detail fetch, by ref code
    assert calls["by_id"] == 0  # the redundant by-id GET is gone
    assert record.isadg_id == 474234  # canonical id comes from the detail object
    metadata = json.loads((tmp_path / "items" / "474234" / "metadata.json").read_text())
    assert metadata["referenceCode"] == "IMC 1954/RoD/1/1737/550"
    assert "searchHit" not in metadata  # output is built only from the detail object


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

    fetch_resource(client(), archive, search_hit, search_id="s1", context_pages=0, images=True)
    fetch_resource(client(), archive, dict(search_hit, isadgID=474234), search_id="s2", context_pages=0, images=True)
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

    record = fetch_resource(client, archive, search_hit, search_id="s", context_pages=1, images=True)

    roles = {r.page_key: r.role for r in record.pages}
    assert roles["IMC_1954_RoD_1_Page_253.jpg"] == "primary"
    assert roles["before.jpg"] == "context"
    assert roles["after.jpg"] == "context"
    assert (tmp_path / "pages" / "208925" / "before.jpg").exists()
    assert (tmp_path / "pages" / "208925" / "after.jpg").exists()
    import json as _json
    vol = _json.loads((tmp_path / "pages" / "208925" / "volume.json").read_text())
    assert vol["reference_code"] == "IMC 1954/RoD/1"
    assert vol["title"] is None  # root detail 208925 is not mocked -> graceful fallback
    assert [p["page_key"] for p in vol["pages"]] == ["before.jpg", "IMC_1954_RoD_1_Page_253.jpg", "after.jpg"]
    assert vol["pages"][1]["label"] == "IMC 1954/RoD/1/1737/550"


def test_fetch_resource_writes_volume_title_from_root_detail(tmp_path):
    from vtextract.archive import Archive

    root_manifest = {
        "label": "TNA SP 63/356",
        "metadata": [{"label": "ReferenceCode", "value": "TNA SP 63/356"}],
        "sequences": [{"canvases": [
            {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288",
             "label": "IMC 1954/RoD/1/1737/550", "width": 826, "height": 1368,
             "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg"}}],
             "otherContent": [{"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"}]},
        ]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/iiif/v1/208925/manifest":
            return httpx.Response(200, json=root_manifest)
        if path == "/rest/isadg-identity-statements/208925":
            # the volume root's own descriptive title
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path.startswith("/loris/"):
            return httpx.Response(200, content=b"\xff\xd8img")
        return _handler(request)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    fetch_resource(client, archive, {"isadgID": 474234, "displayReferenceCode": "X", "displayTitle": "Y"},
                   search_id="s", context_pages=1, images=True)

    vol = json.loads((tmp_path / "pages" / "208925" / "volume.json").read_text())
    assert vol["title"] == "Will of MITCHELL, CALEB, Dublin, carpenter, created 18 January 1724"


def test_refresh_unverified_when_head_raises(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    img = _item_image()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/loris/") and request.method == "HEAD":
            return httpx.Response(404)  # client.head -> raise_for_status raises
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=_item_json("manifest"))
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/"):  # GET
            return httpx.Response(200, content=img)
        return httpx.Response(404, text=path)

    def client():
        return Client(base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
                      user_agent="UA", transport=httpx.MockTransport(handler),
                      delay=0.0, max_retries=0, sleep_func=lambda _s: None)

    # seed the page on disk
    fetch_resource(client(), archive, hit, search_id="s", context_pages=0, images=True)
    img_path = tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg"
    before = img_path.read_bytes()

    outcomes = []
    fetch_resource(client(), archive, hit, search_id="s", context_pages=0, refresh=True, images=True,
                   on_verify=lambda o, p: outcomes.append(o))
    assert outcomes == ["unverified"]       # HEAD raised -> unverified
    assert img_path.read_bytes() == before  # file left untouched


def _refresh_client(calls, *, head_len):
    """Client whose handler counts HEAD/GET on /loris/ and answers item routes.

    head_len: the Content-Length the HEAD response advertises for the image.
    """
    img = _item_image()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/loris/") and request.method == "HEAD":
            calls["head"] += 1
            headers = {} if head_len is None else {"content-length": str(head_len)}
            return httpx.Response(200, headers=headers)
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=_item_json("manifest"))
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/"):  # GET
            calls["get"] += 1
            return httpx.Response(200, content=img)
        return httpx.Response(404, text=path)

    return Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )


def test_refresh_verifies_without_redownload_when_size_matches(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    img_len = len(_item_image())

    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, images=True)
    assert calls == {"head": 0, "get": 1}  # initial archive: one image GET, no HEAD

    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=True)
    assert calls == {"head": 1, "get": 0}  # size matches: HEAD only, no re-download

    # Test B: confirm the matching-size path reports "ok" via on_verify
    ok_outcomes = []
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=True,
                   on_verify=lambda o, p: ok_outcomes.append(o))
    assert ok_outcomes == ["ok"]


def test_refresh_redownloads_on_size_mismatch(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=0), archive, hit,
                   search_id="s", context_pages=0, images=True)

    calls = {"head": 0, "get": 0}
    outcomes = []
    fetch_resource(_refresh_client(calls, head_len=len(_item_image()) + 1), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=True,
                   on_verify=lambda outcome, path: outcomes.append(outcome))
    assert calls == {"head": 1, "get": 1}  # HEAD said different size -> re-download
    assert outcomes == ["mismatch"]


def test_refresh_downloads_missing_image_without_head(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=0), archive, hit,
                   search_id="s", context_pages=0, images=True)
    # delete the image file on disk -> "missing"
    (tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg").unlink()

    calls = {"head": 0, "get": 0}
    outcomes = []
    fetch_resource(_refresh_client(calls, head_len=999), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=True,
                   on_verify=lambda o, p: outcomes.append(o))
    assert calls == {"head": 0, "get": 1}  # missing -> download, no HEAD
    assert outcomes == ["missing"]


def test_refresh_unverified_when_no_content_length(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=0), archive, hit,
                   search_id="s", context_pages=0, images=True)

    calls = {"head": 0, "get": 0}
    outcomes = []
    fetch_resource(_refresh_client(calls, head_len=None), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=True,
                   on_verify=lambda o, p: outcomes.append(o))
    assert calls == {"head": 1, "get": 0}  # no content-length -> unverified, file untouched
    assert outcomes == ["unverified"]


def test_refresh_dedupes_verified_pages_across_calls(tmp_path):
    from vtextract.archive import Archive
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    img_len = len(_item_image())
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, images=True)

    verified: set[str] = set()
    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=True, _verified_pages=verified)
    assert calls["head"] == 1
    calls = {"head": 0, "get": 0}
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=True, _verified_pages=verified)
    assert calls["head"] == 0  # page already verified this run -> not re-HEADed


def test_fetch_resource_without_images_skips_image_bytes(tmp_path):
    """images=False: transcription + metadata only; no Loris GET; state records the mode."""
    from vtextract.archive import Archive

    calls = {"loris_get": 0, "list": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, content=_item_json("manifest"))
        if path == "/iiif/v1/208925/list/197350":
            calls["list"] += 1
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/") and request.method == "GET":
            calls["loris_get"] += 1
            return httpx.Response(200, content=_item_image())
        return httpx.Response(404, text=path)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}

    fetch_resource(client, archive, hit, search_id="s", context_pages=0, images=False)

    page_dir = tmp_path / "pages" / "208925"
    assert not (page_dir / "IMC_1954_RoD_1_Page_253.jpg").exists()  # no image
    assert (page_dir / "IMC_1954_RoD_1_Page_253.jpg.txt").exists()  # transcription written
    assert calls["loris_get"] == 0
    assert calls["list"] == 1  # annotation list still fetched
    assert archive.is_resource_complete(474234, want_images=False) is True
    assert archive.is_resource_complete(474234, want_images=True) is False


def test_fetch_resource_backfills_image_on_second_run_with_images(tmp_path):
    """First run images=False (no Loris); second run images=True downloads the image."""
    from vtextract.archive import Archive

    calls = {"loris_get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/loris/") and request.method == "GET":
            calls["loris_get"] += 1
            return httpx.Response(200, content=_item_image())
        return _handler(request)

    def client():
        return Client(
            base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
            user_agent="UA", transport=httpx.MockTransport(handler),
            delay=0.0, sleep_func=lambda _s: None,
        )

    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}

    fetch_resource(client(), archive, hit, search_id="s", context_pages=0, images=False)
    assert calls["loris_get"] == 0

    fetch_resource(client(), archive, hit, search_id="s", context_pages=0, images=True)
    assert calls["loris_get"] == 1  # image now downloaded
    img_path = tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg"
    assert img_path.exists()
    assert archive.is_resource_complete(474234, want_images=True) is True


def test_fetch_resource_without_images_backfills_missing_transcription(tmp_path):
    """If a transcription file is missing on disk, images=False still downloads it."""
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}

    # First run with images=True puts both on disk.
    fetch_resource(_client(), archive, hit, search_id="s", context_pages=0, images=True)
    txt_path = tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg.txt"
    txt_path.unlink()
    assert not txt_path.exists()

    calls = {"loris_get": 0, "list": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/iiif/v1/208925/list/197350":
            calls["list"] += 1
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/") and request.method == "GET":
            calls["loris_get"] += 1
            return httpx.Response(200, content=_item_image())
        return _handler(request)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    fetch_resource(client, archive, hit, search_id="s", context_pages=0, images=False)
    assert txt_path.exists()
    assert calls["list"] == 1
    assert calls["loris_get"] == 0  # transcription backfill must not pull the image


def test_refresh_without_images_skips_head_and_image_download(tmp_path):
    """refresh without --images: re-fetch manifests, leave images alone, no HEAD."""
    from vtextract.archive import Archive

    img_len = len(_item_image())
    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}

    # Seed an imaged archive.
    fetch_resource(_refresh_client({"head": 0, "get": 0}, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, images=True)
    img_path = tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg"
    before = img_path.read_bytes()

    calls = {"head": 0, "get": 0}
    outcomes = []
    fetch_resource(_refresh_client(calls, head_len=img_len), archive, hit,
                   search_id="s", context_pages=0, refresh=True, images=False,
                   on_verify=lambda o, p: outcomes.append(o))
    assert calls == {"head": 0, "get": 0}  # no HEAD, no GET on Loris
    assert outcomes == []                  # nothing verified
    assert img_path.read_bytes() == before  # image untouched


def test_refresh_without_images_backfills_missing_transcription(tmp_path):
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    hit = {"isadgID": 474234}
    fetch_resource(_client(), archive, hit, search_id="s", context_pages=0, images=False)
    txt_path = tmp_path / "pages" / "208925" / "IMC_1954_RoD_1_Page_253.jpg.txt"
    txt_path.unlink()

    calls = {"loris_get": 0, "list": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/iiif/v1/208925/list/197350":
            calls["list"] += 1
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/"):
            calls["loris_get"] += 1
            return httpx.Response(200, content=_item_image())
        return _handler(request)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    fetch_resource(client, archive, hit, search_id="s", context_pages=0,
                   refresh=True, images=False)
    assert txt_path.exists()
    assert calls["loris_get"] == 0
    assert calls["list"] == 1


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

    record = fetch_resource(client, archive, search_hit, search_id="s", context_pages=1, images=True)

    assert record.pages == []
    assert calls["loris"] == 0
    assert archive.is_resource_complete(474234) is True


# --- image-page allowlist (export backfill restricts downloads to selected pages) ---

_MULTIPAGE_MANIFEST = {
    "label": "Volume-sized resource with two pages",
    "metadata": [{"label": "ReferenceCode", "value": "IMC 1954/RoD/1"}],
    "sequences": [{"canvases": [
        {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p1",
         "label": "page one", "width": 826, "height": 1368,
         "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/page_one.jpg/full/full/0/default.jpg"}}],
         "otherContent": [{"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"}]},
        {"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p2",
         "label": "page two", "width": 826, "height": 1368,
         "images": [{"resource": {"@id": "https://by2022-prod.adaptcentre.ie/loris/page_two.jpg/full/full/0/default.jpg"}}],
         "otherContent": [{"@id": "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"}]},
    ]}],
}


def _multipage_client(loris_gets: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, json=_MULTIPAGE_MANIFEST)
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/") and request.method == "GET":
            loris_gets.append(path)
            return httpx.Response(200, content=_item_image())
        return httpx.Response(404, text=path)

    return Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )


def test_fetch_resource_image_pages_restricts_image_downloads(tmp_path):
    """image_pages allowlist: only the named page's image is downloaded; the
    other page still gets its metadata + transcription."""
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    loris_gets: list[str] = []
    fetch_resource(
        _multipage_client(loris_gets), archive, {"isadgID": 474234},
        search_id="s", context_pages=0, images=True,
        image_pages={"page_one.jpg"},
    )

    page_dir = tmp_path / "pages" / "208925"
    assert (page_dir / "page_one.jpg").exists()          # selected -> downloaded
    assert not (page_dir / "page_two.jpg").exists()      # not selected -> skipped
    assert (page_dir / "page_two.jpg.txt").exists()      # transcription still written
    assert loris_gets == ["/loris/page_one.jpg/full/full/0/default.jpg"]


def test_fetch_resource_image_pages_none_downloads_all(tmp_path):
    """image_pages=None (default) preserves the download-everything behaviour."""
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    loris_gets: list[str] = []
    fetch_resource(
        _multipage_client(loris_gets), archive, {"isadgID": 474234},
        search_id="s", context_pages=0, images=True,
    )
    assert sorted(loris_gets) == [
        "/loris/page_one.jpg/full/full/0/default.jpg",
        "/loris/page_two.jpg/full/full/0/default.jpg",
    ]


def test_fetch_resource_image_pages_restricts_refresh_verify(tmp_path):
    """Under --refresh, the allowlist also limits which images are HEAD-verified."""
    from vtextract.archive import Archive

    archive = Archive(tmp_path)
    # First seed both images.
    fetch_resource(_multipage_client([]), archive, {"isadgID": 474234},
                   search_id="s", context_pages=0, images=True)

    heads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "HEAD" and path.startswith("/loris/"):
            heads.append(path)
            return httpx.Response(200, headers={"Content-Length": str(len(_item_image()))})
        if path == "/rest/isadg-identity-statements/474234":
            return httpx.Response(200, content=_item_json("isadg-identity-statements"))
        if path == "/iiif/v1/474234/manifest":
            return httpx.Response(200, json=_MULTIPAGE_MANIFEST)
        if path == "/iiif/v1/208925/list/197350":
            return httpx.Response(200, content=_item_json("list"))
        if path.startswith("/loris/") and request.method == "GET":
            return httpx.Response(200, content=_item_image())
        return httpx.Response(404, text=path)

    client = Client(
        base_url="https://by2022-prod.adaptcentre.ie", auth_header="Basic x",
        user_agent="UA", transport=httpx.MockTransport(handler),
        delay=0.0, sleep_func=lambda _s: None,
    )
    fetch_resource(client, archive, {"isadgID": 474234}, search_id="s",
                   context_pages=0, refresh=True, images=True,
                   image_pages={"page_one.jpg"})
    assert heads == ["/loris/page_one.jpg/full/full/0/default.jpg"]
