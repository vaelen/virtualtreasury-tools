# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

from vtextract.tui.bundle import Bundle, PageRef


def _ref(root: str, key: str) -> PageRef:
    return PageRef(root_id=root, page_key=key)


def test_empty_bundle_has_no_pages():
    b = Bundle()
    assert b.is_in_bundle(_ref("0007", "p1.jpg")) is False
    assert b.effective_pages() == []


def test_select_item_adds_its_pages():
    b = Bundle()
    b.toggle_item(18425, [_ref("0007", "p4.jpg"), _ref("0007", "p5.jpg")])
    assert b.is_in_bundle(_ref("0007", "p4.jpg")) is True
    assert b.is_in_bundle(_ref("0007", "p5.jpg")) is True


def test_toggle_item_removes_when_already_selected():
    b = Bundle()
    pages = [_ref("0007", "p4.jpg")]
    b.toggle_item(18425, pages)
    b.toggle_item(18425, pages)
    assert b.is_in_bundle(_ref("0007", "p4.jpg")) is False


def test_two_items_share_a_page_ref_counted():
    b = Bundle()
    b.toggle_item(1, [_ref("0007", "p4.jpg"), _ref("0007", "p5.jpg")])
    b.toggle_item(2, [_ref("0007", "p5.jpg"), _ref("0007", "p6.jpg")])
    b.toggle_item(2, [_ref("0007", "p5.jpg"), _ref("0007", "p6.jpg")])  # deselect 2
    assert b.is_in_bundle(_ref("0007", "p5.jpg")) is True   # still wanted by 1
    assert b.is_in_bundle(_ref("0007", "p6.jpg")) is False  # nothing wants it


def test_toggle_page_excludes_when_in_bundle_then_includes_again():
    b = Bundle()
    p = _ref("0007", "p4.jpg")
    b.toggle_item(1, [p])
    b.toggle_page(p)
    assert b.is_in_bundle(p) is False
    assert b.page_state[p] == "exclude"
    b.toggle_page(p)
    assert b.is_in_bundle(p) is True
    assert b.page_state[p] == "include"


def test_exclude_is_sticky_across_item_churn():
    b = Bundle()
    p = _ref("0007", "p5.jpg")
    b.toggle_item(1, [p])
    b.toggle_page(p)             # explicit exclude
    b.toggle_item(1, [p])        # deselect item
    b.toggle_item(1, [p])        # re-select item
    assert b.is_in_bundle(p) is False  # still excluded


def test_manual_include_persists_after_item_deselect():
    b = Bundle()
    p = _ref("0007", "p9.jpg")
    b.toggle_page(p)             # manual include
    assert b.is_in_bundle(p) is True
    # No item ever contributed it; toggling a different item shouldn't drop it.
    b.toggle_item(99, [_ref("0007", "px.jpg")])
    assert b.is_in_bundle(p) is True


def test_effective_pages_is_a_stable_sorted_list():
    b = Bundle()
    b.toggle_item(1, [_ref("0007", "p4.jpg"), _ref("0007", "p2.jpg")])
    b.toggle_item(2, [_ref("0001", "p1.jpg")])
    assert b.effective_pages() == [
        _ref("0001", "p1.jpg"),
        _ref("0007", "p2.jpg"),
        _ref("0007", "p4.jpg"),
    ]


def test_roundtrip_json():
    b = Bundle()
    p1, p2 = _ref("0007", "p4.jpg"), _ref("0007", "p5.jpg")
    b.toggle_item(18425, [p1, p2])
    b.toggle_page(p2)  # exclude
    data = json.loads(b.to_json())
    restored = Bundle.from_json(json.dumps(data))
    assert restored.is_in_bundle(p1) is True
    assert restored.is_in_bundle(p2) is False
    assert restored.page_state == b.page_state
    assert restored.selected_items == b.selected_items


def test_from_json_rejects_unknown_version():
    import pytest
    with pytest.raises(ValueError):
        Bundle.from_json(json.dumps({"version": 99,
                                     "selected_items": [],
                                     "page_state": []}))
