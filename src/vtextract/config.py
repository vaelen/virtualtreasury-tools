from __future__ import annotations

import base64
import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://by2022-prod.adaptcentre.ie"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:151.0) "
    "Gecko/20100101 Firefox/151.0"
)
DEFAULT_INDEX_DB_NAME = "beyond_2022"


@dataclass
class Config:
    auth_header: str
    base_url: str = DEFAULT_BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    index_db_name: str = DEFAULT_INDEX_DB_NAME
    delay: float = 0.5
    max_retries: int = 3


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from environment variables.

    Credentials: set VT_AUTH to the base64 'user:pass' token, OR set both
    VT_USERNAME and VT_PASSWORD. Optional: VT_BASE_URL, VT_USER_AGENT,
    VT_INDEX_DB_NAME, VT_DELAY, VT_MAX_RETRIES.
    """
    env = os.environ if env is None else env

    token = env.get("VT_AUTH")
    if not token:
        username = env.get("VT_USERNAME")
        password = env.get("VT_PASSWORD")
        if username and password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
    if not token:
        raise ValueError(
            "Missing credentials: set VT_AUTH (base64 user:pass token) "
            "or VT_USERNAME and VT_PASSWORD."
        )

    return Config(
        auth_header=f"Basic {token}",
        base_url=env.get("VT_BASE_URL", DEFAULT_BASE_URL),
        user_agent=env.get("VT_USER_AGENT", DEFAULT_USER_AGENT),
        index_db_name=env.get("VT_INDEX_DB_NAME", DEFAULT_INDEX_DB_NAME),
        delay=float(env.get("VT_DELAY", "0.5")),
        max_retries=int(env.get("VT_MAX_RETRIES", "3")),
    )
