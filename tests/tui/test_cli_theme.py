# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""vtbrowse's entry point loads the saved theme, hands it to the app, and
writes the live theme back to the config on exit — only when it changed."""

from __future__ import annotations

import pytest

from vtextract import config as config_mod
from vtextract.tui import cli


class FakeApp:
    """Stand-in for VtBrowseApp: records the theme it was launched with and
    lets a test simulate the user picking a different one before exit."""

    instances: list["FakeApp"] = []
    final_theme: str | None = None  # what .run() leaves on app.theme

    def __init__(self, *, archive, initial_theme=None):
        self.archive = archive
        self.initial_theme = initial_theme
        self.theme = initial_theme
        FakeApp.instances.append(self)

    def run(self):
        if FakeApp.final_theme is not None:
            self.theme = FakeApp.final_theme
        return 0


@pytest.fixture
def fake_app(monkeypatch):
    FakeApp.instances = []
    FakeApp.final_theme = None
    # main() imports VtBrowseApp lazily from vtextract.tui.app at call time.
    monkeypatch.setattr("vtextract.tui.app.VtBrowseApp", FakeApp)
    return FakeApp


def test_saved_theme_is_passed_to_app(tmp_path, fake_app):
    cfg = tmp_path / "vt.toml"
    config_mod.set_browse_theme(cfg, "gruvbox")
    fake_app.final_theme = "gruvbox"  # user leaves it unchanged

    rc = cli.main(["--archive", str(tmp_path / "arch"), "--config", str(cfg)])

    assert rc == 0
    assert fake_app.instances[0].initial_theme == "gruvbox"


def test_changed_theme_is_persisted_on_exit(tmp_path, fake_app):
    cfg = tmp_path / "vt.toml"
    config_mod.set_browse_theme(cfg, "gruvbox")
    fake_app.final_theme = "nord"  # user switches theme during the session

    cli.main(["--archive", str(tmp_path / "arch"), "--config", str(cfg)])

    assert config_mod.load_config(cfg).browse_theme == "nord"


def test_unchanged_theme_does_not_rewrite_config(tmp_path, fake_app):
    cfg = tmp_path / "vt.toml"  # no file written: default theme, never touched
    fake_app.final_theme = config_mod.DEFAULT_BROWSE_THEME

    cli.main(["--archive", str(tmp_path / "arch"), "--config", str(cfg)])

    assert not cfg.exists()
