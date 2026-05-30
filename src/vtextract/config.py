# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import base64
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://by2022-prod.adaptcentre.ie"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:151.0) "
    "Gecko/20100101 Firefox/151.0"
)
DEFAULT_INDEX_DB_NAME = "beyond_2022"
DEFAULT_ARCHIVE = "~/.vt/archive"
DEFAULT_BROWSE_THEME = "textual-dark"


def default_config_path() -> Path:
    """The config file location, ``~/.vt/vt.toml`` with ``~`` expanded."""
    return Path("~/.vt/vt.toml").expanduser()


@dataclass
class Config:
    auth_header: str | None = None
    archive: Path = field(default_factory=lambda: Path(DEFAULT_ARCHIVE).expanduser())
    base_url: str = DEFAULT_BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    index_db_name: str = DEFAULT_INDEX_DB_NAME
    delay: float = 0.5
    max_retries: int = 3
    browse_theme: str = DEFAULT_BROWSE_THEME


def make_token(username: str, password: str) -> str:
    """Return the base64 ``user:pass`` token for HTTP Basic auth."""
    return base64.b64encode(f"{username}:{password}".encode()).decode()


def _read_raw(path: Path) -> dict:
    """Parse the TOML config file, returning ``{}`` if it does not exist."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}


def load_config(path: Path | None = None) -> Config:
    """Build a Config from the TOML file at ``path`` (default ``~/.vt/vt.toml``).

    The shared archive location lives at the top level; vtextract's own
    settings are namespaced under ``[extract.auth]`` and ``[extract.http]``.
    A missing file yields all defaults with ``auth_header`` unset.
    """
    path = default_config_path() if path is None else path
    data = _read_raw(path)
    extract = data.get("extract", {})
    auth = extract.get("auth", {})
    http = extract.get("http", {})

    token = auth.get("token")
    archive = data.get("archive", DEFAULT_ARCHIVE)
    browse = data.get("browse", {})

    return Config(
        auth_header=f"Basic {token}" if token else None,
        archive=Path(archive).expanduser(),
        base_url=http.get("base_url", DEFAULT_BASE_URL),
        user_agent=http.get("user_agent", DEFAULT_USER_AGENT),
        index_db_name=http.get("index_db_name", DEFAULT_INDEX_DB_NAME),
        delay=float(http.get("delay", 0.5)),
        max_retries=int(http.get("max_retries", 3)),
        browse_theme=browse.get("theme", DEFAULT_BROWSE_THEME),
    )


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _toml_table(header: str | None, table: dict) -> list[str]:
    lines: list[str] = []
    if header is not None:
        lines.append(f"[{header}]")
    for key, value in table.items():
        lines.append(f"{key} = {_toml_value(value)}")
    return lines


def write_config(path: Path, data: dict) -> None:
    """Write ``data`` to ``path`` as TOML, creating ``~/.vt`` mode 0700.

    Emits top-level scalar keys first, then the ``[extract.auth]`` /
    ``[extract.http]`` tables, then the ``[browse]`` table. The file is written
    mode 0600 since it holds a credential. Every known table is round-tripped,
    so writing one setting (e.g. via ``set_token``) never drops another.
    """
    top = {k: v for k, v in data.items() if not isinstance(v, dict)}
    blocks: list[list[str]] = []
    if top:
        blocks.append(_toml_table(None, top))
    extract = data.get("extract", {})
    for name in ("auth", "http"):
        sub = extract.get(name)
        if sub:
            blocks.append(_toml_table(f"extract.{name}", sub))
    browse = data.get("browse")
    if browse:
        blocks.append(_toml_table("browse", browse))

    text = "\n\n".join("\n".join(block) for block in blocks)
    if text:
        text += "\n"

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text)
    path.chmod(0o600)


def set_token(path: Path, token: str) -> None:
    """Store ``token`` in ``[extract.auth].token``, preserving other settings."""
    data = _read_raw(path)
    data.setdefault("extract", {}).setdefault("auth", {})["token"] = token
    write_config(path, data)


def set_browse_theme(path: Path, theme: str) -> None:
    """Store ``theme`` in ``[browse].theme``, preserving other settings."""
    data = _read_raw(path)
    data.setdefault("browse", {})["theme"] = theme
    write_config(path, data)
