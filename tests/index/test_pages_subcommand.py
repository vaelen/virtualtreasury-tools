# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import json
import subprocess


def _run(archive, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "vtindex", "pages", *args, "--archive", str(archive), "--json"],
        capture_output=True, text=True, check=False,
    )


def test_pages_lists_volume_pages_in_ordinal_order(built_archive):
    root_id = built_archive["root_id"]
    result = _run(built_archive["path"], root_id)
    assert result.returncode == 0, result.stderr
    pages = json.loads(result.stdout)
    assert pages, "expected at least one page"
    ordinals = [p["ordinal"] for p in pages]
    assert ordinals == sorted(ordinals)
    p = pages[0]
    assert set(p) >= {"ordinal", "page_key", "label", "root_id",
                      "image", "transcription", "metadata"}
    assert p["root_id"] == root_id


def test_pages_unknown_root_returns_exit_1(built_archive):
    result = _run(built_archive["path"], "0000")
    assert result.returncode == 1
    assert json.loads(result.stdout) == []
