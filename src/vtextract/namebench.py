# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import tomllib
from collections import Counter
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
    SIDECAR_SCHEMA,
    Person,
    Usage,
    people_and_usage,
    sum_usage,
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

# A trivial one-sentence document sent to a model before its real files. The
# first call to a model (especially a cold local one) pays load/connection
# latency that would otherwise pollute the timed run, so we send this first and
# throw the result away -- it is never timed and never written as a sidecar.
WARMUP_TEXT = "John Smith met Mary Jones in Dublin in 1850."


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


def write_sidecar(path: Path, model: str, people: list[Person],
                  usage: Usage | None = None) -> None:
    payload: dict = {
        "schema": SIDECAR_SCHEMA,
        "model": model,
        "people": [p.model_dump() for p in people],
    }
    if usage is not None:  # omit when untracked, so it's never read as 0 tokens
        payload["usage"] = usage.to_dict()
    _write_json_atomic(path, payload)


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
) -> tuple[list[Person], Usage | None]:
    """Run the identical names pipeline over one text: chunk -> find -> merge.

    Returns (merged people, summed token usage). All-or-nothing: any chunk
    failure raises (the caller leaves no sidecar so the file retries next run),
    matching ``vtextract names`` behaviour.
    """
    find = find or llm_module.find_people
    groups: list[list[Person]] = []
    usages: list[Usage | None] = []
    chunks = chunk_text(text, chunk_size, overlap)
    for index, (window, _offset) in enumerate(chunks):
        try:
            people, usage = people_and_usage(find(window, model, api_base))
        except Exception as exc:
            raise RuntimeError(f"chunk {index + 1}/{len(chunks)} failed: {exc}") from exc
        groups.append(people)
        usages.append(usage)
    return merge_people(groups), sum_usage(usages)


def _input_txt_files(input_dir: Path) -> list[Path]:
    """Top-level ``*.txt`` files in the input folder, sorted by name."""
    return sorted(p for p in Path(input_dir).glob("*.txt") if p.is_file())


def _is_ollama(model: str) -> bool:
    """True for locally-served Ollama models (which load/unload on the GPU)."""
    return model.startswith("ollama/")


def _log_failure(progress: Progress | None, message: str) -> None:
    """Report a failure, printing above a live progress bar if one is active."""
    if progress is not None:
        progress.console.print(message)
    else:
        print(message, file=sys.stderr)


def partition_files(
    input_dir: Path, model: str, *, force: bool = False,
) -> tuple[list[tuple[Path, Path]], int]:
    """Split a model's input files into (todo, done_count).

    ``todo`` is the list of (txt_path, sidecar_path) needing extraction (sidecar
    missing, or every file when ``force``); ``done_count`` is how many already
    have a sidecar. This is the single definition of the skip rule, shared by
    ``run_model`` and the CLI's per-model progress line.
    """
    md = model_dir(input_dir, model)
    todo: list[tuple[Path, Path]] = []
    done = 0
    for txt in _input_txt_files(input_dir):
        side = sidecar_path(md, txt.name)
        if side.exists() and not force:
            done += 1
        else:
            todo.append((txt, side))
    return todo, done


def warm_up(
    model: str,
    *,
    chunk_size: int = 64000,
    overlap: int = 512,
    api_base: str | None = None,
    find: FindFn | None = None,
) -> None:
    """Prime a model with ``WARMUP_TEXT`` so its first *timed* file is warm.

    Runs the real extraction path but records nothing: the result and any error
    are discarded (a genuine problem resurfaces on the first real file, or was
    already caught by ``check_model``). Never raises.
    """
    try:
        extract_people(WARMUP_TEXT, model, chunk_size=chunk_size,
                       overlap=overlap, api_base=api_base, find=find)
    except Exception:
        pass


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

    When there is work to do, sends an uncounted/untimed ``WARMUP_TEXT`` request
    first so cold-start latency does not skew the first file's timing.
    """
    input_dir = Path(input_dir)
    md = model_dir(input_dir, model)
    md.mkdir(parents=True, exist_ok=True)
    times = load_times(md)

    todo, _done = partition_files(input_dir, model, force=force)
    if todo:
        warm_up(model, chunk_size=chunk_size, overlap=overlap,
                api_base=api_base, find=find)

    def process(txt: Path, side: Path, progress: Progress | None) -> None:
        start = time.perf_counter()
        try:
            people, usage = extract_people(
                txt.read_text(), model,
                chunk_size=chunk_size, overlap=overlap, api_base=api_base, find=find)
        except Exception as exc:
            reason = llm_module.friendly_error(exc, model, api_base)
            _log_failure(progress, f"namebench: failed {model} {txt.name}: {reason}")
            return
        elapsed = time.perf_counter() - start
        write_sidecar(side, model, people, usage)
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
    # Files where the model returned zero persons (recall / "gave up" signal).
    empty_files: int
    # Extraction volume: distinct persons and their aliases, summed over files.
    persons: int
    aliases: int
    # Shape ratios. aliases_per_person is None when no persons were found.
    aliases_per_person: float | None
    persons_per_file: float | None
    # Quality vs the cross-model consensus ground truth (a name is "true" when a
    # strict majority of models extracted it from that file). None when there is
    # no consensus to score against (e.g. a lone model). precision = found names
    # that are consensus; recall = consensus names found; f1 their harmonic mean.
    precision: float | None
    recall: float | None
    f1: float | None
    # Per-file wall-time distribution (seconds); None when no timings recorded.
    min_s: float | None
    max_s: float | None
    median_s: float | None
    mean_s: float | None
    # Length-normalized throughput: total time / total input bytes, in ms/byte.
    ms_per_byte: float | None
    # Output-normalized throughput: total time / persons, in seconds/name.
    # More meaningful than ms/byte because generation latency scales with the
    # number of names emitted, not the input length. None without persons/times.
    s_per_name: float | None
    # Token usage summed across the model's files. None when no sidecar recorded
    # usage (older runs) so it reads as "unknown", not "0 tokens". cached is the
    # subset of in served from a prompt cache (cache hits).
    tokens_in: int | None
    tokens_out: int | None
    tokens_cached: int | None


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


def count_names(people: list[Person]) -> tuple[int, int]:
    """Return ``(persons, aliases)``: how many people were extracted and the
    total number of aliases across them (the canonical name is not an alias)."""
    persons = len(people)
    aliases = sum(len(person.aliases) for person in people)
    return persons, aliases


_HONORIFICS = re.compile(
    r"\b(?:esq(?:uire|r)?|mr|mrs|miss|ms|sir|lord|lady|capt|col|dr|rev|widow"
    r"|mons|madam|corp|sgt|gen|maj|lt)\b\.?",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    """Fold a canonical name to a comparison key for cross-model agreement:
    lowercase, drop honorifics/titles and punctuation, collapse whitespace."""
    s = _HONORIFICS.sub(" ", name.lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class _ModelData:
    """One model's on-disk aggregates, kept for the cross-model consensus pass."""
    files: int = 0
    empty_files: int = 0
    persons: int = 0
    aliases: int = 0
    name_sets: dict[str, set[str]] = None  # input file -> normalized name keys
    total_s: float = 0.0
    total_bytes: int = 0
    timing: list[float] = None
    # Token usage summed over sidecars that recorded it. ``has_usage`` stays
    # False when no sidecar carried a usage block (older runs), so the report
    # shows n/a rather than a misleading 0.
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    has_usage: bool = False


def _read_model_data(input_dir: Path, model: str) -> _ModelData:
    """Read every sidecar + times.json for one model into a ``_ModelData``."""
    md = model_dir(input_dir, model)
    data = _ModelData(name_sets={})
    for side in sorted(md.glob("*" + _SIDECAR_SUFFIX)):
        try:
            payload = json.loads(side.read_text())
        except (OSError, ValueError):
            continue
        data.files += 1
        people = [Person.model_validate(p) for p in payload.get("people", [])]
        p_count, a_count = count_names(people)
        if p_count == 0:
            data.empty_files += 1
        data.persons += p_count
        data.aliases += a_count
        txt_name = side.name[: -len(_SIDECAR_SUFFIX)]
        keys = {k for k in (normalize_name(p.canonical) for p in people) if k}
        data.name_sets[txt_name] = keys
        usage = payload.get("usage")
        if isinstance(usage, dict):
            data.has_usage = True
            data.tokens_in += int(usage.get("in", 0))
            data.tokens_out += int(usage.get("out", 0))
            data.tokens_cached += int(usage.get("cached", 0))
    times = load_times(md)
    data.timing = list(times.values())
    for name, secs in times.items():
        try:
            data.total_bytes += (Path(input_dir) / name).stat().st_size
        except OSError:
            continue  # input file gone; can't length-normalize this one
        data.total_s += secs
    return data


def _consensus_truth(per_model: dict[str, _ModelData]) -> dict[str, set[str]]:
    """Per input file, the set of normalized names a strict majority of the
    models that processed that file agreed on -- the scoring ground truth."""
    files: set[str] = set()
    for data in per_model.values():
        files |= set(data.name_sets)
    truth: dict[str, set[str]] = {}
    for fname in files:
        present = [d for d in per_model.values() if fname in d.name_sets]
        majority = max(2, len(present) // 2 + 1)
        votes: Counter[str] = Counter()
        for d in present:
            votes.update(d.name_sets[fname])  # a set: one vote per model
        truth[fname] = {name for name, n in votes.items() if n >= majority}
    return truth


def _score(data: _ModelData, truth: dict[str, set[str]]
           ) -> tuple[float | None, float | None, float | None]:
    """Precision/recall/F1 of one model's names against the consensus truth.

    All three are None when no consensus names exist to score against (so a lone
    model, or an all-empty corpus, reports no quality metrics rather than 0s).
    """
    hits = found = expected = 0
    for fname, names in data.name_sets.items():
        t = truth.get(fname, set())
        hits += len(names & t)
        found += len(names)
        expected += len(t)
    if expected == 0:
        return None, None, None
    precision = hits / found if found else 0.0
    recall = hits / expected
    denom = precision + recall
    f1 = (2 * precision * recall / denom) if denom else 0.0
    return precision, recall, f1


def build_report(input_dir: Path) -> list[ReportRow]:
    """One ReportRow per model dir with on-disk data, aggregated from sidecars.

    Quality columns (precision/recall/F1) are scored against a cross-model
    consensus ground truth, so this reads every model before emitting any row.
    """
    models = discover_models(input_dir)
    per_model = {m: _read_model_data(input_dir, m) for m in models}
    truth = _consensus_truth(per_model)

    rows: list[ReportRow] = []
    for model in models:
        data = per_model[model]
        precision, recall, f1 = _score(data, truth)
        vals = data.timing
        ms_per_byte = (data.total_s * 1000.0 / data.total_bytes
                       ) if data.total_bytes else None
        rows.append(ReportRow(
            model=model, files=data.files, empty_files=data.empty_files,
            persons=data.persons, aliases=data.aliases,
            aliases_per_person=(data.aliases / data.persons) if data.persons else None,
            persons_per_file=(data.persons / data.files) if data.files else None,
            precision=precision, recall=recall, f1=f1,
            min_s=min(vals) if vals else None,
            max_s=max(vals) if vals else None,
            median_s=statistics.median(vals) if vals else None,
            mean_s=statistics.mean(vals) if vals else None,
            ms_per_byte=ms_per_byte,
            s_per_name=(data.total_s / data.persons) if (data.persons and vals) else None,
            tokens_in=data.tokens_in if data.has_usage else None,
            tokens_out=data.tokens_out if data.has_usage else None,
            tokens_cached=data.tokens_cached if data.has_usage else None))
    return rows


def render_report(rows: list[ReportRow], console: Console | None = None) -> None:
    """Print a Rich table comparing models on extraction volume and timing.

    Quality columns (P/R/F1) score each model against a cross-model consensus
    ground truth (a name is "true" when a strict majority of models extracted it
    from a file). Count columns describe *what* each model extracted: persons,
    aliases, the alias-to-person ratio, persons-per-file, and how many files came
    back empty (a recall / "gave up" signal). Confidence labels are deliberately
    omitted -- they are model-specific and not comparable across providers.

    Timing columns are the per-file wall-time distribution (min/max/median/mean
    seconds) plus two normalizations: ms/byte (per input length) and s/name (per
    person emitted). s/name is usually the more meaningful of the two, since
    generation latency scales with the number of names produced, not input size.
    """
    # Fixed wide width so the table never truncates model names when the output
    # is piped/captured (where Rich would otherwise assume 80 cols).
    console = console or Console(width=220)
    table = Table(title="Name-extraction model comparison")
    table.add_column("Model", justify="left", no_wrap=True)
    for col in ("P", "R", "F1", "Files", "Empty", "Persons", "Aliases",
                "Al/Per", "Per/File", "Min s", "Max s", "Median s", "Mean s",
                "ms/byte", "s/name", "Tok in", "Tok out", "Cached"):
        table.add_column(col, justify="right")

    def fmt(v: float | None, spec: str = "{:.2f}") -> str:
        return "n/a" if v is None else spec.format(v)

    def fmt_int(v: int | None) -> str:
        return "n/a" if v is None else f"{v:,}"

    for r in rows:
        table.add_row(
            r.model, fmt(r.precision), fmt(r.recall), fmt(r.f1),
            str(r.files), str(r.empty_files), str(r.persons),
            str(r.aliases), fmt(r.aliases_per_person), fmt(r.persons_per_file),
            fmt(r.min_s), fmt(r.max_s), fmt(r.median_s), fmt(r.mean_s),
            fmt(r.ms_per_byte, "{:.3f}"), fmt(r.s_per_name),
            fmt_int(r.tokens_in), fmt_int(r.tokens_out), fmt_int(r.tokens_cached))
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
    # Manage real local models (warm-up + unload) only on the production path;
    # an injected `find` (tests) talks to no real provider, so there is nothing
    # to load or evict. prev_local holds the (model, api_base) currently resident.
    manage = find is None
    prev_local: tuple[str, str | None] | None = None

    for i, model in enumerate(bench.models, 1):
        api_base = bench.api_base.get(model)
        todo, done = partition_files(bench.input, model, force=args.force)
        if not todo:
            print(f"namebench: {model} ({i}/{total}): all {done} already done, "
                  f"skipping", file=sys.stderr)
            continue
        print(f"namebench: testing {model} ({i}/{total}): "
              f"{len(todo)} to process, {done} already done", file=sys.stderr)

        if manage:
            # Free the GPU/RAM held by the previous local model before loading
            # this one, then warm up / preflight this model so its first file is
            # not paying the cold-start load cost (and auth errors surface now).
            if prev_local and prev_local[0] != model:
                llm_module.unload(*prev_local)
                prev_local = None
            error = llm_module.check_model(model, api_base)
            if error:
                print(f"namebench: skipping {model}: {error}", file=sys.stderr)
                continue
            if _is_ollama(model):
                prev_local = (model, api_base)

        run_model(
            bench.input, model,
            chunk_size=names_cfg.chunk_size, overlap=names_cfg.overlap,
            api_base=api_base, force=args.force, find=find)

    if manage and prev_local:
        llm_module.unload(*prev_local)   # evict the last local model on the way out

    render_report(build_report(bench.input))
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
