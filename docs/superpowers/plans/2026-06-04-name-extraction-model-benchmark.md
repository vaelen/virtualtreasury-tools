# vtnamebench — Name-extraction model benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `vtnamebench` console tool that runs the exact `vtextract names` extraction over a folder of `.txt` files for several models, writes per-model `.names.json` sidecars + `times.json`, and prints a console report comparing high/medium/low name counts and average time per file.

**Architecture:** One new module `src/vtextract/namebench.py` reusing the real `names` pipeline (`chunk_text`, `find_people`, `merge_people`). Pure helpers (config parse, path mapping, confidence counting, report build) are separated from the I/O loop so they test offline with an injected `find` stub. Registered as a console entry point in `pyproject.toml`.

**Tech Stack:** Python 3.11+ (`tomllib`), `pydantic` models from `vtextract.names.models`, `rich` for the table, `pytest` against `tmp_path` (no network).

---

## File Structure

- **Create** `src/vtextract/namebench.py` — the whole tool: `BenchConfig` + `load_bench_config`, path helpers, atomic sidecar/times writers, `extract_people`, `run_model`, report aggregation (`discover_models`, `count_confidences`, `build_report`, `ReportRow`), `render_report`, and `main`.
- **Create** `tests/test_namebench.py` — offline tests with a stub `find`.
- **Modify** `pyproject.toml` — add `vtnamebench = "vtextract.namebench:main"` under `[project.scripts]`.

Each task below is one TDD cycle. The full module is built incrementally; later tasks import names defined in earlier tasks.

---

## Task 1: Bench config loading

**Files:**
- Create: `src/vtextract/namebench.py`
- Test: `tests/test_namebench.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_namebench.py
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from pathlib import Path

from vtextract.namebench import BenchConfig, load_bench_config


def test_load_bench_config_parses_input_and_models(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        'input = "~/foo/bar"\n'
        'models = ["anthropic/claude-haiku-4-5", "openai/gpt-4.1-mini"]\n'
    )
    bc = load_bench_config(cfg)
    assert isinstance(bc, BenchConfig)
    assert bc.input == Path("~/foo/bar").expanduser()
    assert bc.models == ["anthropic/claude-haiku-4-5", "openai/gpt-4.1-mini"]


def test_load_bench_config_rejects_missing_input(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('models = ["m"]\n')
    try:
        load_bench_config(cfg)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "input" in str(exc)


def test_load_bench_config_rejects_empty_models(tmp_path):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('input = "."\nmodels = []\n')
    try:
        load_bench_config(cfg)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "models" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vtextract.namebench'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/vtextract/namebench.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/namebench.py tests/test_namebench.py
git commit -m "feat(namebench): parse benchmark TOML config"
```

---

## Task 2: Path helpers and atomic sidecar/times writers

**Files:**
- Modify: `src/vtextract/namebench.py`
- Test: `tests/test_namebench.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_namebench.py`)

```python
import json

from vtextract.namebench import (
    model_dir, sidecar_path, times_path, load_times, write_times, write_sidecar,
)
from vtextract.names.models import Person


def test_model_dir_nests_provider_and_model(tmp_path):
    md = model_dir(tmp_path, "anthropic/claude-haiku-4-5")
    assert md == tmp_path / "models" / "anthropic" / "claude-haiku-4-5"


def test_sidecar_and_times_paths(tmp_path):
    md = model_dir(tmp_path, "openai/gpt-4.1")
    assert sidecar_path(md, "1.txt").name == "1.txt.names.json"
    assert times_path(md).name == "times.json"


def test_write_and_load_times_roundtrip(tmp_path):
    md = model_dir(tmp_path, "m")
    md.mkdir(parents=True)
    write_times(md, {"1.txt": 1.5})
    assert load_times(md) == {"1.txt": 1.5}
    # missing file -> empty dict
    assert load_times(model_dir(tmp_path, "other")) == {}


def test_write_sidecar_shape(tmp_path):
    md = model_dir(tmp_path, "m")
    md.mkdir(parents=True)
    people = [Person(canonical="William Young",
                     aliases=[{"text": "Wm Young", "confidence": "high"}])]
    write_sidecar(sidecar_path(md, "1.txt"), "m", people)
    data = json.loads((md / "1.txt.names.json").read_text())
    assert data["schema"] == 1 and data["model"] == "m"
    assert data["people"][0]["canonical"] == "William Young"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: FAIL with `ImportError: cannot import name 'model_dir'`

- [ ] **Step 3: Write minimal implementation** (append to `src/vtextract/namebench.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/namebench.py tests/test_namebench.py
git commit -m "feat(namebench): per-model path helpers and atomic JSON writers"
```

---

## Task 3: `extract_people` — the reused chunk→find→merge pipeline

**Files:**
- Modify: `src/vtextract/namebench.py`
- Test: `tests/test_namebench.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_namebench.py`)

```python
from vtextract.namebench import extract_people


def _fake_find_factory(mapping):
    # mapping: chunk substring -> people list. Mirrors tests/names/test_extractor.py.
    def find(chunk_text, model, api_base=None):
        for needle, people in mapping.items():
            if needle in chunk_text:
                return people
        return []
    return find


def test_extract_people_merges_chunks(tmp_path):
    find = _fake_find_factory({
        "Wm Young": [Person(canonical="William Young",
                            aliases=[{"text": "Wm Young", "confidence": "high"}])],
    })
    people = extract_people("Wm Young paid the toll.", "m", find=find)
    assert [p.canonical for p in people] == ["William Young"]


def test_extract_people_propagates_chunk_failure(tmp_path):
    def boom(chunk_text, model, api_base=None):
        raise RuntimeError("bad json")
    try:
        extract_people("anything", "m", find=boom)
        assert False, "expected the failure to propagate"
    except Exception as exc:
        assert "bad json" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: FAIL with `ImportError: cannot import name 'extract_people'`

- [ ] **Step 3: Write minimal implementation** (append to `src/vtextract/namebench.py`)

```python
from typing import Callable

from vtextract.names import llm as llm_module
from vtextract.names.chunking import chunk_text
from vtextract.names.merge import merge_people

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/namebench.py tests/test_namebench.py
git commit -m "feat(namebench): reuse the names chunk->find->merge pipeline per file"
```

---

## Task 4: `run_model` — sequential per-file processing loop

**Files:**
- Modify: `src/vtextract/namebench.py`
- Test: `tests/test_namebench.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_namebench.py`)

```python
from vtextract.namebench import run_model


def _seed_inputs(tmp_path):
    (tmp_path / "1.txt").write_text("Wm Young paid the toll.")
    (tmp_path / "2.txt").write_text("nothing here")
    return tmp_path


def test_run_model_writes_sidecars_and_times(tmp_path):
    inp = _seed_inputs(tmp_path)
    find = _fake_find_factory({
        "Wm Young": [Person(canonical="William Young",
                            aliases=[{"text": "Wm Young", "confidence": "high"}])],
    })
    run_model(inp, "anthropic/claude-haiku-4-5", find=find)
    md = model_dir(inp, "anthropic/claude-haiku-4-5")
    assert (md / "1.txt.names.json").exists()
    assert (md / "2.txt.names.json").exists()
    times = load_times(md)
    assert set(times) == {"1.txt", "2.txt"}
    assert all(isinstance(v, (int, float)) and v >= 0 for v in times.values())


def test_run_model_skips_existing_and_preserves_time(tmp_path):
    inp = _seed_inputs(tmp_path)
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    # pre-existing sidecar + recorded time for 1.txt
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])
    write_times(md, {"1.txt": 99.0})

    calls = []
    def find(chunk_text, model, api_base=None):
        calls.append(chunk_text)
        return []
    run_model(inp, "m", find=find)
    # 1.txt skipped (find never saw its text); only 2.txt processed
    assert "Wm Young paid the toll." not in calls
    times = load_times(md)
    assert times["1.txt"] == 99.0          # preserved
    assert "2.txt" in times                # newly recorded


def test_run_model_force_reprocesses(tmp_path):
    inp = _seed_inputs(tmp_path)
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [])

    seen = []
    def find(chunk_text, model, api_base=None):
        seen.append(chunk_text)
        return []
    run_model(inp, "m", find=find, force=True)
    assert any("Wm Young" in s for s in seen)  # 1.txt re-read despite sidecar


def test_run_model_logs_failure_and_continues(tmp_path, capsys):
    inp = _seed_inputs(tmp_path)
    def find(chunk_text, model, api_base=None):
        if "Wm Young" in chunk_text:
            raise RuntimeError("boom")
        return []
    run_model(inp, "m", find=find)
    md = model_dir(inp, "m")
    assert not (md / "1.txt.names.json").exists()   # failed file: no sidecar
    assert "1.txt" not in load_times(md)             # and no time entry
    assert (md / "2.txt.names.json").exists()        # other file still processed
    err = capsys.readouterr().err
    assert "1.txt" in err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: FAIL with `ImportError: cannot import name 'run_model'`

- [ ] **Step 3: Write minimal implementation** (append to `src/vtextract/namebench.py`)

```python
import sys
import time


def _input_txt_files(input_dir: Path) -> list[Path]:
    """Top-level ``*.txt`` files in the input folder, sorted by name."""
    return sorted(p for p in Path(input_dir).glob("*.txt") if p.is_file())


def run_model(
    input_dir: Path,
    model: str,
    *,
    chunk_size: int = 64000,
    overlap: int = 512,
    api_base: str | None = None,
    force: bool = False,
    find: FindFn | None = None,
) -> None:
    """Process every input ``*.txt`` for one model, sequentially.

    Skips files whose sidecar already exists unless ``force``. Records per-file
    wall time in ``times.json`` (rewritten after each file so a crash keeps
    completed timings). A file whose extraction fails is logged to stderr and
    left without a sidecar or time entry, so a later run retries it.
    """
    input_dir = Path(input_dir)
    md = model_dir(input_dir, model)
    md.mkdir(parents=True, exist_ok=True)
    times = load_times(md)

    for txt in _input_txt_files(input_dir):
        side = sidecar_path(md, txt.name)
        if side.exists() and not force:
            continue
        start = time.perf_counter()
        try:
            people = extract_people(
                txt.read_text(), model,
                chunk_size=chunk_size, overlap=overlap, api_base=api_base, find=find)
        except Exception as exc:
            reason = llm_module.friendly_error(exc, model, api_base)
            print(f"namebench: failed {model} {txt.name}: {reason}", file=sys.stderr)
            continue
        elapsed = time.perf_counter() - start
        write_sidecar(side, model, people)
        times[txt.name] = elapsed
        write_times(md, times)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/namebench.py tests/test_namebench.py
git commit -m "feat(namebench): sequential per-file run with skip/force/timing/failure handling"
```

---

## Task 5: Report aggregation — discover models, count confidences, build rows

**Files:**
- Modify: `src/vtextract/namebench.py`
- Test: `tests/test_namebench.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_namebench.py`)

```python
from vtextract.namebench import discover_models, count_confidences, build_report


def test_count_confidences_buckets_persons_and_aliases():
    people = [
        Person(canonical="William Young", confidence="high",
               aliases=[{"text": "Wm Young", "confidence": "high"},
                        {"text": "Young", "confidence": "low"}]),
        Person(canonical="J. Smith", confidence="medium", aliases=[]),
    ]
    counts = count_confidences(people)
    # persons: high(William) + medium(J.Smith); aliases: high(Wm) + low(Young)
    assert counts == {"high": 2, "medium": 1, "low": 1}


def test_discover_models_finds_dirs_with_data(tmp_path):
    inp = tmp_path
    a = model_dir(inp, "anthropic/claude-haiku-4-5")
    a.mkdir(parents=True)
    write_sidecar(sidecar_path(a, "1.txt"), "anthropic/claude-haiku-4-5", [])
    b = model_dir(inp, "openai/gpt-4.1")
    b.mkdir(parents=True)
    write_times(b, {"1.txt": 2.0})           # has times but counted as data too
    empty = model_dir(inp, "openai/gpt-4.1-mini")
    empty.mkdir(parents=True)                  # no data -> excluded
    assert discover_models(inp) == [
        "anthropic/claude-haiku-4-5", "openai/gpt-4.1"]


def test_build_report_aggregates_per_model(tmp_path):
    inp = tmp_path
    md = model_dir(inp, "m")
    md.mkdir(parents=True)
    write_sidecar(sidecar_path(md, "1.txt"), "m", [
        Person(canonical="William Young", confidence="high",
               aliases=[{"text": "Wm Young", "confidence": "high"}])])
    write_sidecar(sidecar_path(md, "2.txt"), "m", [])
    write_times(md, {"1.txt": 1.0, "2.txt": 3.0})
    rows = build_report(inp)
    assert len(rows) == 1
    row = rows[0]
    assert row.model == "m"
    assert row.files == 2
    assert row.high == 2 and row.medium == 0 and row.low == 0
    assert row.total == 2
    assert row.avg_seconds == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: FAIL with `ImportError: cannot import name 'discover_models'`

- [ ] **Step 3: Write minimal implementation** (append to `src/vtextract/namebench.py`)

```python
from vtextract.names.models import CONFIDENCE_LEVELS


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: PASS (16 passed)

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/namebench.py tests/test_namebench.py
git commit -m "feat(namebench): report aggregation over on-disk sidecars and timings"
```

---

## Task 6: `render_report` + `main` CLI + entry point

**Files:**
- Modify: `src/vtextract/namebench.py`
- Modify: `pyproject.toml`
- Test: `tests/test_namebench.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_namebench.py`)

```python
from vtextract.namebench import main


def test_main_processes_all_models_and_reports(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("Wm Young paid the toll.")
    cfg = tmp_path / "bench.toml"
    cfg.write_text(
        f'input = "{inp}"\n'
        'models = ["anthropic/claude-haiku-4-5", "openai/gpt-4.1"]\n'
    )
    find = _fake_find_factory({
        "Wm Young": [Person(canonical="William Young", confidence="high",
                            aliases=[{"text": "Wm Young", "confidence": "high"}])],
    })
    rc = main([str(cfg)], find=find)
    assert rc == 0
    # sidecars written for both models
    assert sidecar_path(model_dir(inp, "anthropic/claude-haiku-4-5"), "1.txt").exists()
    assert sidecar_path(model_dir(inp, "openai/gpt-4.1"), "1.txt").exists()
    out = capsys.readouterr().out
    assert "anthropic/claude-haiku-4-5" in out
    assert "openai/gpt-4.1" in out


def test_main_reports_unrun_model_with_existing_data(tmp_path, capsys):
    inp = tmp_path / "data"
    inp.mkdir()
    (inp / "1.txt").write_text("hi")
    # prior-run data for a model NOT in this config
    old = model_dir(inp, "openai/gpt-4.1-mini")
    old.mkdir(parents=True)
    write_sidecar(sidecar_path(old, "1.txt"), "openai/gpt-4.1-mini",
                  [Person(canonical="A B", confidence="low", aliases=[])])
    write_times(old, {"1.txt": 5.0})
    cfg = tmp_path / "bench.toml"
    cfg.write_text(f'input = "{inp}"\nmodels = ["anthropic/claude-haiku-4-5"]\n')

    find = _fake_find_factory({})
    rc = main([str(cfg)], find=find)
    assert rc == 0
    out = capsys.readouterr().out
    # report includes the un-run prior-data model
    assert "openai/gpt-4.1-mini" in out


def test_main_errors_on_bad_config(tmp_path, capsys):
    cfg = tmp_path / "bench.toml"
    cfg.write_text('models = ["m"]\n')   # missing input
    rc = main([str(cfg)], find=_fake_find_factory({}))
    assert rc != 0
    assert "input" in capsys.readouterr().err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: FAIL with `ImportError: cannot import name 'main'`

- [ ] **Step 3: Write minimal implementation** (append to `src/vtextract/namebench.py`)

```python
import argparse

from rich.console import Console
from rich.table import Table

from vtextract.config import load_config


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

    names_cfg = load_config().names  # reuse chunk_size/overlap from [names]
    for model in bench.models:
        run_model(
            bench.input, model,
            chunk_size=names_cfg.chunk_size, overlap=names_cfg.overlap,
            force=args.force, find=find)

    render_report(build_report(bench.input))
    return 0
```

Then add a module entry guard at the very end of the file:

```python
if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Register the console script** — in `pyproject.toml`, under `[project.scripts]`, add the `vtnamebench` line after `vtbrowse`:

```toml
[project.scripts]
vtextract = "vtextract.cli:main"
vtindex = "vtextract.index.cli:main"
vtbrowse = "vtextract.tui.cli:main"
vtnamebench = "vtextract.namebench:main"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_namebench.py -q`
Expected: PASS (19 passed)

- [ ] **Step 6: Verify the entry point resolves**

Run: `uv run vtnamebench --help`
Expected: argparse usage text mentioning `config` and `--force` (exit 0).

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/namebench.py tests/test_namebench.py pyproject.toml
git commit -m "feat(namebench): CLI, console report, and vtnamebench entry point"
```

---

## Task 7: Full-suite check and README note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the whole suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: all tests pass (existing suite + 19 new).

- [ ] **Step 2: Add a short README section** documenting the tool. Find the section describing `vtextract names` and add after it:

```markdown
### Benchmarking models (`vtnamebench`)

`vtnamebench bench.toml` runs the exact `vtextract names` extraction over a
folder of `.txt` files for several models and prints a comparison report.

```toml
# bench.toml
input = "~/foo/bar"
models = [
  "anthropic/claude-haiku-4-5",
  "anthropic/claude-sonnet-4-6",
  "openai/gpt-4.1-mini",
  "openai/gpt-4.1",
]
```

Run with `uv run vtnamebench bench.toml`. For each model it writes
`<input>/models/<model>/<file>.txt.names.json` sidecars and a `times.json`
(filename → seconds), skipping files already processed by that model
(`--force` re-runs). It then prints a table comparing the number of high/
medium/low-confidence names (counting each person and each alias) and the
average time per file, including any model with prior on-disk data.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(namebench): document the vtnamebench benchmark tool"
```

---

## Self-Review notes

- **Spec coverage:** config parse (T1), per-model paths + sidecar/times shape (T2), reused prompt/chunking pipeline (T3), sequential skip/force/timing/failure loop (T4), disk-rescanning report with persons+aliases buckets and prior-data models (T5), CLI + entry point + console table (T6), suite + docs (T7). All spec sections map to a task.
- **Type consistency:** `find` seam signature `(chunk_text, model, api_base=None)` is identical across `extract_people`, `run_model`, and `main`. `ReportRow` fields (`model, files, high, medium, low, total, avg_seconds`) are produced in T5 and consumed unchanged in `render_report` (T6). `model_dir`/`sidecar_path`/`times_path`/`load_times`/`write_times`/`write_sidecar` defined in T2 are reused verbatim in T4–T6 and the tests.
- **No placeholders:** every code step is complete and runnable.
```
