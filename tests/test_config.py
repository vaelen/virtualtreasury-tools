import base64

import pytest

from vtextract.config import Config, load_config


def test_load_config_builds_basic_auth_header_from_token():
    cfg = load_config({"VT_AUTH": "dXNlcjpwYXNz"})  # base64 of "user:pass"
    assert cfg.auth_header == "Basic dXNlcjpwYXNz"
    assert cfg.base_url == "https://by2022-prod.adaptcentre.ie"
    assert cfg.index_db_name == "beyond_2022"


def test_load_config_builds_token_from_user_and_pass():
    cfg = load_config({"VT_USERNAME": "user", "VT_PASSWORD": "pass"})
    expected = base64.b64encode(b"user:pass").decode()
    assert cfg.auth_header == f"Basic {expected}"


def test_load_config_overrides_base_url_and_delay():
    cfg = load_config({"VT_AUTH": "x", "VT_BASE_URL": "https://example.test", "VT_DELAY": "0.5"})
    assert cfg.base_url == "https://example.test"
    assert cfg.delay == 0.5


def test_load_config_missing_credentials_raises():
    with pytest.raises(ValueError, match="VT_AUTH"):
        load_config({})
