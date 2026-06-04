# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from vtextract.config import load_config
from vtextract.names import llm as llm_module
from vtextract.names.chunking import chunk_text
from vtextract.names.merge import merge_people
from vtextract.names.models import (
    CONFIDENCE_LEVELS,
    SIDECAR_SCHEMA,
    Person,
)


@dataclass
class BenchConfig:
    input: Path
    models: list[str]
    api_base: dict[str, str]   # model -> endpoint; unlisted models route by prefix


def load_bench_config(path: Path) -> BenchConfig:
    """Parse the benchmark TOML: an ``input`` folder, a ``models`` list, and an
    optional ``[api_base]`` table mapping a model to a custom endpoint."""
    with Path(path).open("rb") as fh:
        data = tomllib.load(fh)
    raw_input = data.get("input")
    if not raw_input:
        raise ValueError("bench config must set a non-empty 'input' folder")
    models = data.get("models") or []
    if not isinstance(models, list) or not models:
        raise ValueError("bench config must set a non-empty 'models' list")
    api_base = data.get("api_base", {})
    if not isinstance(api_base, dict):
        raise ValueError("bench config 'api_base' must be a table of model -> URL")
    return BenchConfig(
        input=Path(raw_input).expanduser(),
        models=[str(m) for m in models],
        api_base={str(k): str(v) for k, v in api_base.items()},
    )


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


# (chunk_text, model, api_base) -> people for that chunk (same seam as extractor).
FindFn = Callable[[str, str, "str | None"], "list[Person]"]


def extract_people(
    text: str,
    model: str,
    *,
    chunk_size: int = 64000,
    overlap: int = 512,
    api_base: str | None = None,
    find: FindFn | None = None,
) -> list[Person]:
    """Run the identical names pipeline over one text: chunk -> find -> merge.

    All-or-nothing: any chunk failure raises (the caller leaves no sidecar so the
    file retries next run), matching ``vtextract names`` behaviour.
    """
    find = find or llm_module.find_people
    groups: list[list[Person]] = []
    chunks = chunk_text(text, chunk_size, overlap)
    for index, (window, _offset) in enumerate(chunks):
        try:
            groups.append(find(window, model, api_base))
        except Exception as exc:
            raise RuntimeError(f"chunk {index + 1}/{len(chunks)} failed: {exc}") from exc
    return merge_people(groups)


def _input_txt_files(input_dir: Path) -> list[Path]:
    """Top-level ``*.txt`` files in the input folder, sorted by name."""
    return sorted(p for p in Path(input_dir).glob("*.txt") if p.is_file())


def _log_failure(progress: Progress | None, message: str) -> None:
    """Report a failure, printing above a live progress bar if one is active."""
    if progress is not None:
        progress.console.print(message)
    else:
        print(message, file=sys.stderr)


def run_model(
    input_dir: Path,
    model: str,
    *,
    chunk_size: int = 64000,
    overlap: int = 512,
    api_base: str | None = None,
    force: bool = False,
    find: FindFn | None = None,
    show_progress: bool = True,
) -> None:
    """Process every input ``*.txt`` for one model, sequentially.

    Skips files whose sidecar already exists unless ``force``. Records per-file
    wall time in ``times.json`` (rewritten after each file so a crash keeps
    completed timings). A file whose extraction fails is logged to stderr and
    left without a sidecar or time entry, so a later run retries it. When
    ``show_progress`` and there is work to do, renders a Rich progress bar
    (labelled with the model) over the files, as ``vtextract names`` does.
    """
    input_dir = Path(input_dir)
    md = model_dir(input_dir, model)
    md.mkdir(parents=True, exist_ok=True)
    times = load_times(md)

    todo: list[tuple[Path, Path]] = []  # (txt_path, sidecar_path)
    for txt in _input_txt_files(input_dir):
        side = sidecar_path(md, txt.name)
        if side.exists() and not force:
            continue
        todo.append((txt, side))

    def process(txt: Path, side: Path, progress: Progress | None) -> None:
        start = time.perf_counter()
        try:
            people = extract_people(
                txt.read_text(), model,
                chunk_size=chunk_size, overlap=overlap, api_base=api_base, find=find)
        except Exception as exc:
            reason = llm_module.friendly_error(exc, model, api_base)
            _log_failure(progress, f"namebench: failed {model} {txt.name}: {reason}")
            return
        elapsed = time.perf_counter() - start
        write_sidecar(side, model, people)
        times[txt.name] = elapsed
        write_times(md, times)

    if show_progress and todo:
        with Progress(console=Console(stderr=True)) as progress:
            task_id = progress.add_task(model, total=len(todo))
            for txt, side in todo:
                process(txt, side, progress)
                progress.advance(task_id)
    else:
        for txt, side in todo:
            process(txt, side, None)


@dataclass
class ReportRow:
    model: str
    files: int
    high: int
    medium: int
    low: int
    total: int
    avg_seconds: float | None   # None when no timings recorded


def discover_models(input_dir: Path) -> list[str]:
    """Model strings under ``<input>/models`` whose dir has a sidecar or times.

    The model string is the dir path relative to ``models/`` (so a two-level
    ``provider/model`` round-trips). Sorted for stable report order.
    """
    models_root = Path(input_dir) / "models"
    if not models_root.is_dir():
        return []
    found: set[str] = set()
    for d in models_root.rglob("*"):
        if d.is_dir() and ((d / _TIMES_NAME).exists() or any(d.glob("*" + _SIDECAR_SUFFIX))):
            found.add(d.relative_to(models_root).as_posix())
    return sorted(found)


def count_confidences(people: list[Person]) -> dict[str, int]:
    """Bucket every name -- each person's canonical AND each alias -- by its own
    confidence into high/medium/low."""
    counts = {level: 0 for level in CONFIDENCE_LEVELS}
    for person in people:
        counts[person.confidence] += 1
        for alias in person.aliases:
            counts[alias.confidence] += 1
    return counts


def build_report(input_dir: Path) -> list[ReportRow]:
    """One ReportRow per model dir with on-disk data, aggregated from sidecars."""
    rows: list[ReportRow] = []
    for model in discover_models(input_dir):
        md = model_dir(input_dir, model)
        totals = {level: 0 for level in CONFIDENCE_LEVELS}
        files = 0
        for side in sorted(md.glob("*" + _SIDECAR_SUFFIX)):
            try:
                data = json.loads(side.read_text())
            except (OSError, ValueError):
                continue
            files += 1
            people = [Person.model_validate(p) for p in data.get("people", [])]
            for level, n in count_confidences(people).items():
                totals[level] += n
        times = list(load_times(md).values())
        avg = sum(times) / len(times) if times else None
        rows.append(ReportRow(
            model=model, files=files,
            high=totals["high"], medium=totals["medium"], low=totals["low"],
            total=totals["high"] + totals["medium"] + totals["low"],
            avg_seconds=avg))
    return rows


def render_report(rows: list[ReportRow], console: Console | None = None) -> None:
    """Print a Rich table comparing models on name counts and avg time/file."""
    console = console or Console()
    table = Table(title="Name-extraction model comparison")
    for col in ("Model", "Files", "High", "Med", "Low", "Total", "Avg s/file"):
        table.add_column(col, justify="right" if col != "Model" else "left")
    for r in rows:
        avg = "n/a" if r.avg_seconds is None else f"{r.avg_seconds:.2f}"
        table.add_row(r.model, str(r.files), str(r.high), str(r.medium),
                      str(r.low), str(r.total), avg)
    if not rows:
        console.print("namebench: no model data found.")
        return
    console.print(table)


def main(argv: list[str] | None = None, *, find: FindFn | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="vtnamebench",
        description="Compare LLMs on the vtextract names person-extraction task.")
    parser.add_argument("config", help="path to the benchmark TOML config")
    parser.add_argument("--force", action="store_true",
                        help="re-process files even if a sidecar already exists")
    args = parser.parse_args(argv)

    try:
        bench = load_bench_config(Path(args.config))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"namebench: bad config: {exc}", file=sys.stderr)
        return 2
    if not bench.input.is_dir():
        print(f"namebench: input folder not found: {bench.input}", file=sys.stderr)
        return 2

    n_files = len(_input_txt_files(bench.input))
    print(f"Found {n_files} file{'' if n_files == 1 else 's'}.", file=sys.stderr)

    names_cfg = load_config().names  # reuse chunk_size/overlap from [names]
    total = len(bench.models)
    for i, model in enumerate(bench.models, 1):
        print(f"namebench: testing {model} ({i}/{total})", file=sys.stderr)
        run_model(
            bench.input, model,
            chunk_size=names_cfg.chunk_size, overlap=names_cfg.overlap,
            api_base=bench.api_base.get(model),
            force=args.force, find=find)

    render_report(build_report(bench.input))
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
