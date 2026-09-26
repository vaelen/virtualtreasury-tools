# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "archive"


def test_fixture_archive_has_expected_items_and_pages():
    items = sorted(p.name for p in (FIXTURE / "items").iterdir())
    assert items == ["100", "200", "300"]
    # volume.json present for both volumes
    assert (FIXTURE / "pages" / "volA" / "volume.json").exists()
    assert (FIXTURE / "pages" / "volB" / "volume.json").exists()
    # item 100 references a page that has transcription text on disk
    meta = json.loads((FIXTURE / "items" / "100" / "metadata.json").read_text())
    assert meta["isadgID"] == 100
    primary = [p for p in meta["pages"] if p["role"] == "primary"]
    assert primary and (
        FIXTURE / "pages" / primary[0]["root_id"] / f'{primary[0]["page_key"]}.txt'
    ).exists()
