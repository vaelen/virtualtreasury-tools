# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
import subprocess


def _run(archive, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "vtindex", "item", *args, "--archive", str(archive), "--json"],
        capture_output=True, text=True, check=False,
    )


def test_item_returns_record_with_role_per_page(built_archive):
    result = _run(built_archive["path"], str(built_archive["isadg_id"]))
    assert result.returncode == 0, result.stderr
    item = json.loads(result.stdout)
    assert item["isadg_id"] == built_archive["isadg_id"]
    assert "title" in item and "reference_code" in item
    assert isinstance(item["pages"], list) and item["pages"]
    roles = {p["role"] for p in item["pages"]}
    assert roles <= {"primary", "context"}
    p = item["pages"][0]
    assert set(p) >= {"root_id", "page_key", "role"}


def test_item_unknown_id_returns_exit_1(built_archive):
    result = _run(built_archive["path"], "999999999")
    assert result.returncode == 1
    assert json.loads(result.stdout) is None
