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


import json
import os

from vtextract.names.models import SIDECAR_SCHEMA, Person

_SIDECAR_SUFFIX = ".names.json"
_TIMES_NAME = "times.json"


def model_dir(input_dir: Path, model: str) -> Path:
    """Per-model output dir: ``<input>/models/<model>`` (model nests on '/')."""
    return Path(input_dir) / "models" / model


def sidecar_path(md: Path, txt_name: str) -> Path:
    """``<txt_name>.names.json`` inside the model dir (keeps the .txt)."""
    return Path(md) / (txt_name + _SIDECAR_SUFFIX)


def times_path(md: Path) -> Path:
    return Path(md) / _TIMES_NAME


def _write_json_atomic(path: Path, data: object) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def load_times(md: Path) -> dict[str, float]:
    try:
        return json.loads(times_path(md).read_text())
    except (OSError, ValueError):
        return {}


def write_times(md: Path, times: dict[str, float]) -> None:
    _write_json_atomic(times_path(md), times)


def write_sidecar(path: Path, model: str, people: list[Person]) -> None:
    _write_json_atomic(path, {
        "schema": SIDECAR_SCHEMA,
        "model": model,
        "people": [p.model_dump() for p in people],
    })
