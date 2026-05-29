# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Key bindings avoid terminal-level collisions: export is not on ctrl+shift+s
(delivered as ctrl+s, colliding with Save) and info is not on ctrl+i (byte-
identical to Tab)."""

from __future__ import annotations

from vtextract.tui.app import VtBrowseApp


def _bindings() -> dict[str, str]:
    return {b.key: b.action for b in VtBrowseApp.BINDINGS}


def test_export_rebound_off_ctrl_shift_s():
    b = _bindings()
    assert "ctrl+shift+s" not in b
    assert b.get("ctrl+w") == "export_bundle"
    # Save stays on ctrl+s.
    assert b.get("ctrl+s") == "save_bundle"


def test_info_rebound_off_ctrl_i():
    b = _bindings()
    assert "ctrl+i" not in b
    assert b.get("i") == "open_info"
