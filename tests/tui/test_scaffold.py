# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

import subprocess


def test_vtbrowse_help_exits_zero():
    result = subprocess.run(["uv", "run", "vtbrowse", "--help"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "vtbrowse" in result.stdout.lower()


def test_vtbrowse_module_importable():
    import vtextract.tui  # noqa: F401
    import vtextract.tui.cli  # noqa: F401
