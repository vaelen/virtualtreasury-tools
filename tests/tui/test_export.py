# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json
import tarfile
import zipfile
from pathlib import Path

from vtextract.tui.bundle import Bundle, PageRef
from vtextract.tui.export import export_bundle


def test_export_folder_writes_expected_layout(tmp_archive, tmp_path):
    bundle = Bundle()
    bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg"),
                             PageRef("volA", "volA_p0.jpg")])
    out = tmp_path / "bundle_test"
    result = export_bundle(bundle=bundle, archive=tmp_archive,
                           destination=out, include_images=False)
    assert result == out
    vol_dir = out / "volA"
    assert (vol_dir / "volume.json").exists()
    # volA_p1.jpg has a .txt transcription; no .json page meta in fixtures.
    assert (vol_dir / "volA_p1.jpg.txt").exists()
    assert (vol_dir / "volA_p0.jpg.txt").exists()
    # Images are opt-in; the fixture has no images anyway, but assert no file.
    assert not (vol_dir / "volA_p1.jpg").exists()
    # Top-level bundle.json round-trips.
    assert (out / "bundle.json").exists()
    restored = Bundle.from_json((out / "bundle.json").read_text())
    assert 100 in restored.selected_items


def test_export_includes_names_sidecar(tmp_archive, tmp_path):
    # The names sidecar is copied verbatim alongside the page's .txt/.json —
    # including its schema/model metadata, not just the people list.
    sidecar = {"schema": 2, "model": "test", "people": [["John Smith", "Jno. Smith"]]}
    (tmp_archive / "pages" / "volA" / "volA_p1.jpg.names.json").write_text(
        json.dumps(sidecar))
    bundle = Bundle()
    bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg"),
                             PageRef("volA", "volA_p0.jpg")])
    out = tmp_path / "bundle_test"
    export_bundle(bundle=bundle, archive=tmp_archive,
                  destination=out, include_images=False)
    exported = out / "volA" / "volA_p1.jpg.names.json"
    assert exported.exists()
    assert json.loads(exported.read_text()) == sidecar
    # Pages without a sidecar export without one, and without erroring.
    assert not (out / "volA" / "volA_p0.jpg.names.json").exists()


def test_export_zip_writes_archive(tmp_archive, tmp_path):
    bundle = Bundle()
    bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg")])
    dest = tmp_path / "bundle_test.zip"
    result = export_bundle(bundle=bundle, archive=tmp_archive,
                           destination=dest, include_images=False, fmt="zip")
    assert result == dest
    assert dest.exists()
    with zipfile.ZipFile(dest) as z:
        names = set(z.namelist())
    assert "bundle.json" in names
    assert "volA/volume.json" in names
    assert "volA/volA_p1.jpg.txt" in names
    # Staging directory cleaned up.
    assert not (tmp_path / "bundle_test.staging").exists()


def test_export_targz_writes_archive(tmp_archive, tmp_path):
    bundle = Bundle()
    bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg")])
    dest = tmp_path / "bundle_test.tar.gz"
    result = export_bundle(bundle=bundle, archive=tmp_archive,
                           destination=dest, include_images=False, fmt="targz")
    assert result == dest
    assert dest.exists()
    with tarfile.open(dest, "r:gz") as tf:
        names = set(tf.getnames())
    # tarball entries are relative to the staging root.
    assert any(n.endswith("bundle.json") for n in names)
    assert any(n.endswith("volA/volume.json") for n in names)
    assert any(n.endswith("volA/volA_p1.jpg.txt") for n in names)


def test_export_bundle_json_round_trip(tmp_archive, tmp_path):
    bundle = Bundle()
    bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg")])
    bundle.toggle_item(200, [PageRef("volA", "volA_p1.jpg"),
                             PageRef("volB", "volB_p5.jpg")])
    bundle.toggle_page(PageRef("volA", "volA_p0.jpg"))  # explicit include
    out = tmp_path / "bundle_test"
    export_bundle(bundle=bundle, archive=tmp_archive,
                  destination=out, include_images=False)
    restored = Bundle.from_json((out / "bundle.json").read_text())
    assert 100 in restored.selected_items
    assert 200 in restored.selected_items
    assert restored.is_in_bundle(PageRef("volA", "volA_p0.jpg"))


def test_export_unknown_format_raises(tmp_archive, tmp_path):
    bundle = Bundle()
    out = tmp_path / "bundle_bad"
    try:
        export_bundle(bundle=bundle, archive=tmp_archive,
                      destination=out, include_images=False, fmt="bogus")
    except ValueError as exc:
        assert "bogus" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown fmt")


def test_export_includes_notes_sidecar(tmp_archive, tmp_path):
    # The hand-written notes.md travels with the page; absence is fine.
    (tmp_archive / "pages" / "volA" / "volA_p1.jpg.notes.md").write_text("J. Smith is James.")
    bundle = Bundle()
    bundle.toggle_item(100, [PageRef("volA", "volA_p1.jpg"),
                             PageRef("volA", "volA_p0.jpg")])
    out = tmp_path / "bundle_test"
    export_bundle(bundle=bundle, archive=tmp_archive,
                  destination=out, include_images=False)
    assert (out / "volA" / "volA_p1.jpg.notes.md").read_text() == "J. Smith is James."
    assert not (out / "volA" / "volA_p0.jpg.notes.md").exists()
