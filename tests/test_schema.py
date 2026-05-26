import pytest

from vtextract.schema import extract_root_id


def test_extract_root_id_from_canvas_id():
    canvas_id = "https://by2022-prod.adaptcentre.ie/iiif/v1/208925/canvas/p235288"
    assert extract_root_id(canvas_id) == "208925"


def test_extract_root_id_raises_when_absent():
    with pytest.raises(ValueError):
        extract_root_id("https://example.test/no/volume/here")
