# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
import subprocess


def test_search_matched_pages_include_role(built_archive_with_search_hit):
    result = subprocess.run(
        ["uv", "run", "vtindex", "search", built_archive_with_search_hit["query"],
         "--archive", str(built_archive_with_search_hit["path"]), "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert rows, "expected at least one match"
    pages = rows[0]["matched_pages"]
    assert pages, "expected at least one matched page"
    assert {"root_id", "page_key", "role"} <= set(pages[0])
    assert pages[0]["role"] in {"primary", "context"}
