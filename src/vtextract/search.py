# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from collections.abc import Iterator

from vtextract.models import SearchCriteria


def criteria_to_params(criteria: SearchCriteria) -> dict[str, str | list[str]]:
    """Flatten a SearchCriteria into doc_search query params.

    The three keyword keys become parallel arrays (one entry per filter);
    the rest are scalars. Keys are omitted when they carry no information so
    we send only what the browser would. resultSorting always has a value.
    """
    params: dict[str, str | list[str]] = {}
    if criteria.filters:
        params["kwList"] = [" ".join(f.keywords) for f in criteria.filters]
        params["kwOperList"] = [f.operand for f in criteria.filters]
        params["kwSearchFieldList"] = [f.field for f in criteria.filters]
    if criteria.start:
        params["searchContentDate_begin"] = criteria.start
    if criteria.end:
        params["searchContentDate_end"] = criteria.end
    if criteria.boost:
        params["boostItemsWithKGEntityType"] = criteria.boost
    params["resultSorting"] = criteria.sorting
    return params


def build_body(
    params: dict[str, str | list[str]],
    *,
    page_number: int,
    page_size: int,
    index_db_name: str,
) -> dict:
    """Construct the JSON body for POST /IR_REST_V2/webapi/doc_search.

    Reproduces the full body the site's JS sends, including the empty-array
    filter scaffolding (searchDocumentRepositoryNameList has no CLI option but
    is always present) and a default resultSorting. Caller params override.
    """
    return {
        "indexDBName": index_db_name,
        "totalElementsInt": page_size,
        "pageNumberInt": page_number,
        "neOperList": [],
        "neComboSetList": [],
        "searchDocumentRepositoryNameList": [],
        "searchLinkTypeList": [],
        "searchThematicCollectionList": [],
        "searchSourceFormatList": [],
        "searchSourceGradeList": [],
        "resultSorting": "relevance",
        **params,
    }


SEARCH_PATH = "/IR_REST_V2/webapi/doc_search"


def iter_results(
    client,
    params: dict[str, str | list[str]],
    *,
    index_db_name: str,
    page_size: int = 100,
) -> Iterator[dict]:
    """Yield every resource record across all pages of a doc_search query."""
    page_number = 0
    seen = 0
    while True:
        body = build_body(
            params,
            page_number=page_number,
            page_size=page_size,
            index_db_name=index_db_name,
        )
        response = client.post_json(SEARCH_PATH, body)
        records = response.get("resultInfoList", [])
        total = response.get("generalInfo", {}).get("totalDocs", 0)
        for record in records:
            yield record
        seen += len(records)
        if not records or seen >= total:
            break
        page_number += 1
