# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import base64
from pathlib import Path

from vtextract.config import (
    DEFAULT_BASE_URL,
    DEFAULT_BROWSE_THEME,
    DEFAULT_INDEX_DB_NAME,
    Config,
    default_config_path,
    load_config,
    make_token,
    set_browse_theme,
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


def test_load_config_browse_theme_defaults_when_absent(tmp_path):
    cfg = load_config(tmp_path / "vt.toml")
    assert cfg.browse_theme == DEFAULT_BROWSE_THEME


def test_load_config_reads_browse_theme(tmp_path):
    path = _write(tmp_path / "vt.toml", '[browse]\ntheme = "nord"\n')
    assert load_config(path).browse_theme == "nord"


def test_set_browse_theme_preserves_token_and_other_settings(tmp_path):
    path = _write(
        tmp_path / "vt.toml",
        'archive = "~/keep/this"\n'
        "\n"
        "[extract.auth]\n"
        'token = "dXNlcjpwYXNz"\n',
    )
    set_browse_theme(path, "gruvbox")
    cfg = load_config(path)
    assert cfg.browse_theme == "gruvbox"
    assert cfg.auth_header == "Basic dXNlcjpwYXNz"
    assert cfg.archive == Path("~/keep/this").expanduser()


def test_set_token_preserves_browse_theme(tmp_path):
    """Regression: write_config must round-trip the [browse] table, or an
    `auth` write would silently drop the saved theme."""
    path = _write(tmp_path / "vt.toml", '[browse]\ntheme = "dracula"\n')
    set_token(path, "bmV3OnRva2Vu")
    cfg = load_config(path)
    assert cfg.auth_header == "Basic bmV3OnRva2Vu"
    assert cfg.browse_theme == "dracula"


def test_names_defaults_when_absent(tmp_path):
    from vtextract.config import load_config
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.names.model == "ollama/llama3.1"
    assert cfg.names.api_base is None
    assert cfg.names.chunk_size == 64000
    assert cfg.names.workers == 1
    assert cfg.names.max_output_tokens == 12000
    assert cfg.names.dense_threshold == 5000
    assert cfg.names.dense_chunk_size == 3000


def test_names_section_parsed(tmp_path):
    from vtextract.config import load_config
    p = tmp_path / "vt.toml"
    p.write_text(
        '[names]\n'
        'model = "anthropic/claude-haiku-4-5"\n'
        'api_base = "http://localhost:11434"\n'
        'chunk_size = 8000\n'
        'workers = 4\n'
        'max_output_tokens = 20000\n'
        'dense_threshold = 4000\n'
        'dense_chunk_size = 2500\n'
    )
    cfg = load_config(p)
    assert cfg.names.model == "anthropic/claude-haiku-4-5"
    assert cfg.names.api_base == "http://localhost:11434"
    assert cfg.names.chunk_size == 8000
    assert cfg.names.workers == 4
    assert cfg.names.max_output_tokens == 20000
    assert cfg.names.dense_threshold == 4000
    assert cfg.names.dense_chunk_size == 2500


def test_ask_defaults_to_names_model(tmp_path):
    from vtextract.config import load_config
    p = tmp_path / "vt.toml"
    p.write_text('[names]\nmodel = "gemini/x"\napi_base = "http://h"\n')
    cfg = load_config(p)
    assert cfg.ask.model == "gemini/x"
    assert cfg.ask.api_base == "http://h"


def test_ask_section_overrides(tmp_path):
    from vtextract.config import load_config
    p = tmp_path / "vt.toml"
    p.write_text('[names]\nmodel = "gemini/x"\n[ask]\nmodel = "gemini/vision"\napi_base = "http://a"\n')
    cfg = load_config(p)
    assert cfg.ask.model == "gemini/vision"
    assert cfg.ask.api_base == "http://a"
    assert cfg.names.model == "gemini/x"
