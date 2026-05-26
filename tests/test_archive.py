from vtextract.archive import Archive


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
