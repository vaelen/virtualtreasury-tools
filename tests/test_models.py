# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from vtextract.models import (
    BOOST_FOR_FIELD,
    FIELD_MAP,
    OPERANDS,
    Filter,
    Page,
    PageRef,
    Record,
    SearchCriteria,
)


def test_record_defaults_to_empty_pages():
    rec = Record(isadg_id=474234, reference_code="IMC 1954/RoD/1/1737/550", title="Will")
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


def test_field_map_covers_every_cli_field_flag():
    assert FIELD_MAP == {
        "keyword": "all",
        "title": "title",
        "transcription": "kwTranscription",
        "creator": "creator",
        "person": "kg_label",
        "place": "kg_label",
        "ref": "referenceCode",
    }


def test_operands_and_boost_maps():
    assert OPERANDS == {"all": "ALL", "any": "ANY", "none": "NONE", "exact": "EXACT"}
    assert BOOST_FOR_FIELD == {"person": "Person", "place": "Place"}


def test_search_criteria_defaults():
    criteria = SearchCriteria(filters=[Filter("title", "ALL", ["houston"])])
    assert criteria.filters[0].keywords == ["houston"]
    assert criteria.start is None
    assert criteria.end is None
    assert criteria.boost is None
    assert criteria.sorting == "relevance"
