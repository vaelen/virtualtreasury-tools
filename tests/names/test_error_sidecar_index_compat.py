# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved
import json

from vtextract.names.extractor import _write_error_sidecar


def test_index_glob_excludes_error_sidecars(tmp_path):
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    # a real success sidecar (should be seen) ...
    (pages / "a.jpg.names.json").write_text(json.dumps(
        {"schema": 1, "model": "m", "people": []}))
    # ... and a parked-failure sidecar (must NOT be seen by the index glob)
    _write_error_sidecar(pages / "b.jpg.txt", model="m", error_class="truncated",
                         finish_reason="length", message="cut off")

    seen = sorted(p.name for p in (tmp_path / "pages").glob("*/*.jpg.names.json"))
    assert seen == ["a.jpg.names.json"]
    assert "b.jpg.names.error.json" not in seen
