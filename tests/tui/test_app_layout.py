# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved


def test_empty_app_layout(snap_compare, tmp_archive):
    """Header above, footer below, Bundle pane + Document pane side by side."""
    from vtextract.tui.app import VtBrowseApp

    assert snap_compare(VtBrowseApp(archive=tmp_archive))
