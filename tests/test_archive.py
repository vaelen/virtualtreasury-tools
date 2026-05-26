# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.archive import Archive
import hashlib


def test_new_archive_has_empty_state(tmp_path):
    archive = Archive(tmp_path)
    assert archive.is_resource_complete(474234) is False
    assert archive.has_page("208925", "x.jpg") is False


def test_state_persists_across_instances(tmp_path):
    archive = Archive(tmp_path)
    archive.mark_resource_complete(474234, pages=[], search_id="houston")
    archive.save_state()

    reopened = Archive(tmp_path)
    assert reopened.is_resource_complete(474234) is True


def test_state_file_written_to_disk(tmp_path):
    archive = Archive(tmp_path)
    archive.mark_resource_failed(999, reason="boom")
    archive.save_state()
    assert (tmp_path / "_state.json").exists()


def test_store_page_writes_files_and_registers(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(
        root_id="208925",
        page_key="p1.jpg",
        image_bytes=b"\xff\xd8jpegbytes",
        text="hello world",
        annotations={"resources": [{"resource": {"chars": "hello world"}}]},
    )
    base = tmp_path / "pages" / "208925"
    assert (base / "p1.jpg").read_bytes() == b"\xff\xd8jpegbytes"
    assert (base / "p1.jpg.txt").read_text() == "hello world"
    assert "hello world" in (base / "p1.jpg.json").read_text()
    assert archive.has_page("208925", "p1.jpg") is True


def test_store_page_records_checksum(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg", image_bytes=b"abc", text=None, annotations=None)
    expected = hashlib.sha256(b"abc").hexdigest()
    assert archive.page_checksum("208925", "p1.jpg") == expected


def test_store_page_without_text_skips_transcription_files(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg", image_bytes=b"abc", text=None, annotations=None)
    base = tmp_path / "pages" / "208925"
    assert (base / "p1.jpg").exists()
    assert not (base / "p1.jpg.txt").exists()
    assert not (base / "p1.jpg.json").exists()


def test_write_volume_info(tmp_path):
    archive = Archive(tmp_path)
    archive.write_volume_info("208925", {"label": "Vol 1", "reference_code": "IMC 1954/RoD/1"})
    import json as _json
    data = _json.loads((tmp_path / "pages" / "208925" / "volume.json").read_text())
    assert data["label"] == "Vol 1"


import json as _json

from vtextract.models import PageRef, Record


def test_write_resource_writes_metadata_and_manifest(tmp_path):
    archive = Archive(tmp_path)
    record = Record(
        isadg_id=474234,
        reference_code="IMC 1954/RoD/1/1737/550",
        title="Will of MITCHELL, CALEB",
        search_hit={"isadgID": 474234},
        detail={"id": 474234},
        pages=[PageRef(page_key="p1.jpg", root_id="208925", role="primary",
                       path="pages/208925/p1.jpg", canvas_label="lbl", width=826, height=1368)],
    )
    archive.write_resource(record, manifest={"@type": "sc:Manifest"})

    item_dir = tmp_path / "items" / "474234"
    metadata = _json.loads((item_dir / "metadata.json").read_text())
    assert metadata["isadgID"] == 474234
    assert metadata["referenceCode"] == "IMC 1954/RoD/1/1737/550"
    assert metadata["searchHit"] == {"isadgID": 474234}
    assert metadata["detail"] == {"id": 474234}
    assert metadata["pages"][0]["page_key"] == "p1.jpg"
    assert metadata["pages"][0]["role"] == "primary"

    manifest = _json.loads((item_dir / "manifest.json").read_text())
    assert manifest["@type"] == "sc:Manifest"


def test_has_page_false_when_file_corrupted(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg",
                       image_bytes=b"abc", text=None, annotations=None)
    assert archive.has_page("208925", "p1.jpg") is True
    (tmp_path / "pages" / "208925" / "p1.jpg").write_bytes(b"corrupted")
    assert archive.has_page("208925", "p1.jpg") is False


def test_has_page_false_when_file_missing(tmp_path):
    archive = Archive(tmp_path)
    archive.store_page(root_id="208925", page_key="p1.jpg",
                       image_bytes=b"abc", text=None, annotations=None)
    (tmp_path / "pages" / "208925" / "p1.jpg").unlink()
    assert archive.has_page("208925", "p1.jpg") is False
