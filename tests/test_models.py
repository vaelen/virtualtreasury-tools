# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.models import Page, PageRef, Record


def test_record_defaults_to_empty_pages():
    rec = Record(isadg_id=474234, reference_code="IMC 1954/RoD/1/1737/550", title="Will", search_hit={})
    assert rec.pages == []
    assert rec.detail is None


def test_page_holds_iiif_fields():
    page = Page(
        page_key="IMC_1954_RoD_1_Page_253.jpg",
        image_url="https://api/loris/IMC_1954_RoD_1_Page_253.jpg/full/full/0/default.jpg",
        annotation_list_urls=["https://api/iiif/v1/208925/list/197350"],
        root_id="208925",
        canvas_id="https://api/iiif/v1/208925/canvas/p235288",
        width=826,
        height=1368,
    )
    assert page.root_id == "208925"
    assert page.annotation_list_urls[0].endswith("197350")


def test_page_ref_records_role_and_path():
    ref = PageRef(
        page_key="x.jpg", root_id="208925", role="primary",
        path="pages/208925/x.jpg", canvas_label="lbl", width=1, height=2,
    )
    assert ref.role == "primary"
    assert ref.path == "pages/208925/x.jpg"
