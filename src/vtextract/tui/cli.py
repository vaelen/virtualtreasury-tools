# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Entry point for the `vtbrowse` TUI. Resolves the archive (same rules
as vtindex/vtextract), then launches the Textual app."""

from __future__ import annotations

import argparse
from pathlib import Path

from vtextract.config import load_config


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


def _resolve_archive(args) -> Path:
    if args.archive:
        return Path(args.archive)
    return load_config(Path(args.config) if args.config else None).archive


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    archive = _resolve_archive(args)
    # The Textual import is deferred so --help / scaffolding tests don't
    # require a working tty.
    from vtextract.tui.app import VtBrowseApp
    return VtBrowseApp(archive=archive).run() or 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
