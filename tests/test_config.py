# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import base64
from pathlib import Path

from vtextract.config import (
    DEFAULT_BASE_URL,
    DEFAULT_INDEX_DB_NAME,
    Config,
    default_config_path,
    load_config,
    make_token,
    set_token,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_load_config_absent_file_uses_defaults(tmp_path):
    cfg = load_config(tmp_path / "vt.toml")
    assert cfg.auth_header is None
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.index_db_name == DEFAULT_INDEX_DB_NAME
    assert cfg.archive == Path("~/.vt/archive").expanduser()


def test_load_config_builds_basic_auth_header_from_token(tmp_path):
    path = _write(
        tmp_path / "vt.toml",
        '[extract.auth]\ntoken = "dXNlcjpwYXNz"\n',  # base64 of "user:pass"
    )
    cfg = load_config(path)
    assert cfg.auth_header == "Basic dXNlcjpwYXNz"


def test_load_config_expands_archive_and_applies_http_overrides(tmp_path):
    path = _write(
        tmp_path / "vt.toml",
        'archive = "~/somewhere/archive"\n'
        "\n"
        "[extract.http]\n"
        'base_url = "https://example.test"\n'
        "delay = 1.5\n"
        "max_retries = 7\n",
    )
    cfg = load_config(path)
    assert cfg.archive == Path("~/somewhere/archive").expanduser()
    assert cfg.base_url == "https://example.test"
    assert cfg.delay == 1.5
    assert cfg.max_retries == 7


def test_make_token_base64_encodes_user_and_pass():
    assert make_token("user", "pass") == base64.b64encode(b"user:pass").decode()


def test_default_config_path_is_in_dot_vt():
    assert default_config_path() == Path("~/.vt/vt.toml").expanduser()


def test_set_token_preserves_other_settings(tmp_path):
    path = _write(
        tmp_path / "vt.toml",
        'archive = "~/keep/this"\n'
        "\n"
        "[extract.http]\n"
        "delay = 2.0\n",
    )
    set_token(path, "bmV3OnRva2Vu")
    cfg = load_config(path)
    assert cfg.auth_header == "Basic bmV3OnRva2Vu"
    assert cfg.archive == Path("~/keep/this").expanduser()
    assert cfg.delay == 2.0


def test_set_token_creates_file_and_restricts_permissions(tmp_path):
    path = tmp_path / "nested" / "vt.toml"
    set_token(path, "dG9rZW4=")
    assert load_config(path).auth_header == "Basic dG9rZW4="
    assert (path.stat().st_mode & 0o777) == 0o600
