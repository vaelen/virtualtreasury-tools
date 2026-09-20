# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Entry point for the `vtbrowse` TUI. Resolves the archive (same rules
as vtindex/vtextract), then launches the Textual app."""

from __future__ import annotations

import argparse
from pathlib import Path

from vtextract.config import default_config_path, load_config, set_browse_theme


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtbrowse",
        description="Browse a vtextract archive, curate a bundle of pages, "
                    "and export the bundle for sharing.",
    )
    parser.add_argument("--archive", help="archive dir "
                        "(default: the config file's archive)")
    parser.add_argument("--config",
                        help="Config file path (default ~/.vt/vt.toml).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config) if args.config else None
    cfg = load_config(config_path)
    archive = Path(args.archive) if args.archive else cfg.archive
    # The Textual import is deferred so --help / scaffolding tests don't
    # require a working tty.
    from vtextract.tui.app import VtBrowseApp
    app = VtBrowseApp(archive=archive, initial_theme=cfg.browse_theme, config=cfg)
    rc = app.run() or 0
    # Persist the theme on exit, but only if the user actually changed it —
    # an untouched run leaves the (credential-bearing) config file alone.
    if app.theme and app.theme != cfg.browse_theme:
        set_browse_theme(config_path or default_config_path(), app.theme)
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
