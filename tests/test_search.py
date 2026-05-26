# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.models import Filter, SearchCriteria
from vtextract.search import build_body, criteria_to_params, iter_results


class FakeSearchClient:
    """Stub Client.post_json that serves two pages of fake results."""

    def __init__(self):
        self.posted = []

    def post_json(self, url, body):
        self.posted.append(body)
        page = body["pageNumberInt"]
        if page == 0:
            return {
                "generalInfo": {"totalDocs": 3, "docNumberPerPage": 2, "currentPage": 1},
                "resultInfoList": [{"isadgID": 1}, {"isadgID": 2}],
            }
        return {
            "generalInfo": {"totalDocs": 3, "docNumberPerPage": 2, "currentPage": 2},
            "resultInfoList": [{"isadgID": 3}],
        }


def test_iter_results_yields_all_records_across_pages():
    client = FakeSearchClient()
    records = list(
        iter_results(
            client,
            {"kwList": "houston"},
            index_db_name="beyond_2022",
            page_size=2,
        )
    )
    assert [r["isadgID"] for r in records] == [1, 2, 3]
    assert client.posted[0]["pageNumberInt"] == 0
    assert client.posted[1]["pageNumberInt"] == 1
    assert len(client.posted) == 2  # stops once totalDocs reached


def test_iter_results_reports_total_once():
    client = FakeSearchClient()
    totals = []
    list(
        iter_results(
            client,
            {"kwList": "houston"},
            index_db_name="beyond_2022",
            page_size=2,
            on_total=totals.append,
        )
    )
    assert totals == [3]  # reported once, even though there are two pages


def test_criteria_to_params_builds_parallel_lists():
    criteria = SearchCriteria(
        filters=[
            Filter("title", "ALL", ["memorial", "houston"]),
            Filter("kwTranscription", "ANY", ["castle", "watchmaker"]),
            Filter("kg_label", "EXACT", ["Dublin"]),
        ]
    )
    params = criteria_to_params(criteria)
    assert params["kwList"] == ["memorial houston", "castle watchmaker", "Dublin"]
    assert params["kwOperList"] == ["ALL", "ANY", "EXACT"]
    assert params["kwSearchFieldList"] == ["title", "kwTranscription", "kg_label"]


def test_criteria_to_params_includes_dates_boost_and_sorting():
    criteria = SearchCriteria(
        filters=[Filter("kg_label", "ALL", ["Dublin"])],
        start="1200-01-01",
        end="1870-12-31",
        boost="Place",
        sorting="descending",
    )
    params = criteria_to_params(criteria)
    assert params["searchContentDate_begin"] == "1200-01-01"
    assert params["searchContentDate_end"] == "1870-12-31"
    assert params["boostItemsWithKGEntityType"] == "Place"
    assert params["resultSorting"] == "descending"


def test_criteria_to_params_omits_unset_scalars_and_empty_filters():
    params = criteria_to_params(SearchCriteria())
    assert "kwList" not in params
    assert "kwOperList" not in params
    assert "kwSearchFieldList" not in params
    assert "searchContentDate_begin" not in params
    assert "boostItemsWithKGEntityType" not in params
    # sorting always has a default and is always sent
    assert params["resultSorting"] == "relevance"


def test_build_body_includes_scaffolding_and_list_values():
    params = {"kwList": ["houston"], "kwOperList": ["ALL"]}
    body = build_body(params, page_number=2, page_size=100, index_db_name="beyond_2022")
    assert body["indexDBName"] == "beyond_2022"
    assert body["kwList"] == ["houston"]
    assert body["kwOperList"] == ["ALL"]
    assert body["pageNumberInt"] == 2
    assert body["totalElementsInt"] == 100
    # the fixed scaffolding the browser always sends
    assert body["neOperList"] == []
    assert body["searchDocumentRepositoryNameList"] == []
    assert body["searchSourceGradeList"] == []
    assert body["resultSorting"] == "relevance"


def test_build_body_params_override_scaffolding_defaults():
    body = build_body(
        {"resultSorting": "ascending"},
        page_number=0, page_size=100, index_db_name="beyond_2022",
    )
    assert body["resultSorting"] == "ascending"
