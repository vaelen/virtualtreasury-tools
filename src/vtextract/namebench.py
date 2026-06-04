# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BenchConfig:
    input: Path
    models: list[str]


def load_bench_config(path: Path) -> BenchConfig:
    """Parse the benchmark TOML: an ``input`` folder and a ``models`` list."""
    with Path(path).open("rb") as fh:
        data = tomllib.load(fh)
    raw_input = data.get("input")
    if not raw_input:
        raise ValueError("bench config must set a non-empty 'input' folder")
    models = data.get("models") or []
    if not isinstance(models, list) or not models:
        raise ValueError("bench config must set a non-empty 'models' list")
    return BenchConfig(input=Path(raw_input).expanduser(), models=[str(m) for m in models])
