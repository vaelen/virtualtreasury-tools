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
