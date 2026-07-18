# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Write a Bundle to disk as a folder, zip, or tar.gz.

Pure file I/O — no subprocess. Image backfill via `vtextract get` is
deferred to Task 21. Layout::

    bundle_*/<root_id>/{volume.json, <page_key>.{txt,json,[names.json],[image]}}
    bundle_*/bundle.json
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from vtextract.tui.archive_reader import ArchiveReader
from vtextract.tui.bundle import Bundle


def export_bundle(*, bundle: Bundle, archive: Path, destination: Path,
                  include_images: bool, fmt: str = "folder") -> Path:
    """Write ``bundle`` to ``destination`` in the requested format.

    fmt: ``'folder'`` | ``'zip'`` | ``'targz'``. For ``'zip'`` / ``'targz'``
    the destination is the archive filename (extension chosen by caller).
    Returns the actual path written to.
    """
    if fmt not in ("folder", "zip", "targz"):
        raise ValueError(f"unknown fmt: {fmt}")
    reader = ArchiveReader(archive)
    staging = destination if fmt == "folder" else destination.with_suffix(".staging")
    staging.mkdir(parents=True, exist_ok=True)

    by_vol: dict[str, list] = {}
    for p in bundle.effective_pages():
        by_vol.setdefault(p.root_id, []).append(p)

    for root_id, pages in sorted(by_vol.items()):
        vol_out = staging / root_id
        vol_out.mkdir(exist_ok=True)
        vol_meta = reader.read_volume_meta(root_id) or {}
        (vol_out / "volume.json").write_text(json.dumps(vol_meta, indent=2))
        for ref in pages:
            txt = reader.read_transcription(ref.root_id, ref.page_key)
            if txt is not None:
                (vol_out / f"{ref.page_key}.txt").write_text(txt)
            meta = reader.read_page_meta(ref.root_id, ref.page_key)
            if meta is not None:
                (vol_out / f"{ref.page_key}.json").write_text(
                    json.dumps(meta, indent=2))
            names = reader.names_path(ref.root_id, ref.page_key)
            if names.exists():
                shutil.copy2(names, vol_out / names.name)
            if include_images and reader.image_exists(ref.root_id, ref.page_key):
                shutil.copy2(reader.image_path(ref.root_id, ref.page_key),
                             vol_out / ref.page_key)

    (staging / "bundle.json").write_text(bundle.to_json())

    if fmt == "folder":
        return staging
    if fmt == "zip":
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
            for f in staging.rglob("*"):
                z.write(f, f.relative_to(staging))
        shutil.rmtree(staging)
        return destination
    # fmt == "targz"
    # `shutil.make_archive` appends the extension itself.
    base = str(destination).removesuffix(".tar.gz")
    shutil.make_archive(base, "gztar", root_dir=staging)
    shutil.rmtree(staging)
    return destination
