from vtextract.search import parse_search_url


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
