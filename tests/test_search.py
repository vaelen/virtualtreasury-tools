from vtextract.search import parse_search_url, build_body


def test_parse_search_url_extracts_query_params():
    url = (
        "https://virtualtreasury.ie/search-results?totalElementsInt=100&pageNumberInt=0"
        "&kwList=houston&kwOperList=ALL&searchContentDate_begin=1650-01-01"
        "&searchContentDate_end=1760-12-31&kwSearchFieldList=kwTranscription"
        "&resultSorting=relevance"
    )
    params = parse_search_url(url)
    assert params["kwList"] == "houston"
    assert params["kwOperList"] == "ALL"
    assert params["searchContentDate_begin"] == "1650-01-01"
    assert params["resultSorting"] == "relevance"
    # pagination params are managed by the tool, not carried from the URL
    assert "pageNumberInt" not in params
    assert "totalElementsInt" not in params


def test_build_body_merges_index_name_and_pagination():
    params = {"kwList": "houston", "kwOperList": "ALL"}
    body = build_body(params, page_number=2, page_size=100, index_db_name="beyond_2022")
    assert body["indexDBName"] == "beyond_2022"
    assert body["kwList"] == "houston"
    assert body["kwOperList"] == "ALL"
    assert body["pageNumberInt"] == 2
    assert body["totalElementsInt"] == 100
