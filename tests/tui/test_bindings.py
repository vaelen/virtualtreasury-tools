# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Global bindings are plain single-key presses — no control modifiers — and
map each action to its agreed mnemonic."""

from __future__ import annotations

from vtextract.tui.app import VtBrowseApp

_EXPECTED = {
    "q": "request_quit",
    "f": "open_search",
    "r": "open_results",
    "v": "open_volumes",
    "i": "open_info",
    "s": "save_bundle",
    "o": "open_bundle",
    "x": "export_bundle",
    "b": "build_index",
    "e": "extract",
}


def _bindings() -> dict[str, str]:
    return {b.key: b.action for b in VtBrowseApp.BINDINGS}


def test_no_control_modifier_bindings():
    keys = _bindings()
    assert not [k for k in keys if k.startswith("ctrl")], (
        f"ctrl bindings remain: {[k for k in keys if k.startswith('ctrl')]}"
    )


def test_action_mnemonics():
    keys = _bindings()
    for key, action in _EXPECTED.items():
        assert keys.get(key) == action, f"{key!r} should run {action!r}"
