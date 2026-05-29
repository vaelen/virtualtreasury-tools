# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

"""Filled out in Task 12. Stubbed here so index_client.py imports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ProgressEvent:
    raw: dict[str, Any]


def parse_event(line: str) -> ProgressEvent:
    return ProgressEvent(raw=json.loads(line))
