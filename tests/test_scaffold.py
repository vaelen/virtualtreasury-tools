# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

def test_package_imports():
    import vtextract
    assert vtextract.__version__ == "0.1.0"
