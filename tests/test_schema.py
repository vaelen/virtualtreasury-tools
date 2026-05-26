import pytest

from vtextract.schema import extract_root_id, loris_filename, parse_manifest, reconstruct_text
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


def test_reconstruct_text_joins_chars_in_order():
    annotation_list = {
        "resources": [
            {"resource": {"@type": "cnt:ContentAsText", "chars": "line one"}},
            {"resource": {"@type": "cnt:ContentAsText", "chars": "line two"}},
        ]
    }
    assert reconstruct_text(annotation_list) == "line one\nline two"


def test_reconstruct_text_from_real_sample_starts_expected():
    sample = load_example_json("item", "list")
    text = reconstruct_text(sample)
    assert "REGISTRY OF DEEDS, DUBLIN" in text
    assert text.splitlines()[0] == "25"


from vtextract.schema import neighbor_canvases


def _root_manifest():
    """Synthetic 4-page volume manifest for deterministic neighbour tests."""
    def canvas(n: int) -> dict:
        return {
            "@id": f"https://api/iiif/v1/208925/canvas/p{n}",
            "label": f"page {n}",
            "width": 10,
            "height": 20,
            "images": [
                {"resource": {"@id": f"https://api/loris/page_{n}.jpg/full/full/0/default.jpg"}}
            ],
            "otherContent": [{"@id": f"https://api/iiif/v1/208925/list/{n}"}],
        }

    return {"sequences": [{"canvases": [canvas(1), canvas(2), canvas(3), canvas(4)]}]}


def test_neighbor_canvases_returns_prev_and_next():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/p2", n=1)
    keys = [p.page_key for p in pages]
    assert keys == ["page_1.jpg", "page_3.jpg"]


def test_neighbor_canvases_clips_at_start_edge():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/p1", n=1)
    assert [p.page_key for p in pages] == ["page_2.jpg"]


def test_neighbor_canvases_clips_at_end_edge():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/p4", n=2)
    assert [p.page_key for p in pages] == ["page_2.jpg", "page_3.jpg"]


def test_neighbor_canvases_unknown_canvas_returns_empty():
    pages = neighbor_canvases(_root_manifest(), "https://api/iiif/v1/208925/canvas/nope", n=1)
    assert pages == []


from vtextract.schema import normalize_record, volume_info


def test_normalize_record_uses_search_hit_fields():
    hit = {
        "isadgID": 474234,
        "displayReferenceCode": "IMC 1954/RoD/1/1737/550",
        "displayTitle": "Will of MITCHELL, CALEB",
    }
    detail = {"id": 474234, "extentAndMedium": "1 will"}
    record = normalize_record(hit, detail)
    assert record.isadg_id == 474234
    assert record.reference_code == "IMC 1954/RoD/1/1737/550"
    assert record.title == "Will of MITCHELL, CALEB"
    assert record.search_hit is hit
    assert record.detail is detail
    assert record.pages == []


def test_volume_info_from_real_manifest():
    manifest = load_example_json("item", "manifest")
    info = volume_info(manifest)
    assert info["label"] == "Will of MITCHELL, CALEB, Dublin, carpenter, created 18 January 1724"
    assert info["reference_code"] == "IMC 1954/RoD/1/1737/550"
