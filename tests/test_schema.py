import pytest

from vtextract.schema import extract_root_id, loris_filename, parse_manifest
from tests.conftest import load_example_json


def test_extract_root_id_from_canvas_id():
    canvas_id = "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288"
    assert extract_root_id(canvas_id) == "208925"


def test_extract_root_id_raises_when_absent():
    with pytest.raises(ValueError):
        extract_root_id("https://example.test/no/volume/here")


def test_loris_filename_from_image_url():
    url = "https://by2022-prod.adaptcentre.ie/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg"
    assert loris_filename(url) == "IMC_1954_RoD_1_Page_253.jpg"


def test_parse_manifest_from_real_sample():
    manifest = load_example_json("item", "manifest")
    pages = parse_manifest(manifest)
    assert len(pages) == 1
    page = pages[0]
    assert page.page_key == "IMC_1954_RoD_1_Page_253.jpg"
    assert page.image_url.endswith("/full/full/0/default.jpg")
    assert page.root_id == "208925"
    assert page.canvas_id.endswith("/canvas/p235288")
    assert page.annotation_list_urls == [
        "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/list/197350"
    ]
    assert page.width == 826
    assert page.height == 1368
