# vtextract person-NER (vtextract names) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `vtextract names` command that uses an LLM to extract people from each page transcription into durable per-page sidecar files, and teach `vtindex` to ingest those sidecars into searchable person tables.

**Architecture:** A new `src/vtextract/names/` subpackage embeds name-grep's LiteLLM wrapper (the single LLM-call boundary), a chunker, and an extractor that walks `archive/pages/**/*.jpg.txt`, calls the model once per page, and writes `{page_key}.names.json` sidecars (skipping pages already done). The sidecars are the precious source of truth; `vtindex build` ingests them into new `person`/`person_alias` tables (+ FTS), and `vtindex people "<name>"` queries them. The index stays freely rebuildable.

**Tech Stack:** Python 3.12, LiteLLM (new dep), Pydantic (new dep), SQLite+FTS5, argparse, rich, pytest.

**Spec:** `docs/superpowers/specs/2026-06-02-vtextract-person-ner-design.md`

**Key facts from the existing code (do not re-derive):**
- Page transcriptions live at `archive/pages/<root_id>/<page_key>.txt`, where `page_key` already ends in `.jpg` (so files are `*.jpg.txt`). Annotations are `<page_key>.json`. Our sidecar is `<page_key>.names.json`.
- The index DB (`src/vtextract/index/db.py`) is the single SQL choke point; `SCHEMA_VERSION` is currently **3** and must bump to **4**. Source files are fingerprinted in `source_file(path, kind, mtime, size)`; `delete_source` switches on `kind`.
- Builder `_candidates()` enumerates source files; `_index_one()` switches on `kind`. Relpaths are archive-relative POSIX strings like `pages/<root_id>/<page_key>.jpg.txt`.
- Config (`src/vtextract/config.py`) `load_config()` reads `~/.vt/vt.toml`; top-level `archive`, plus `[extract.*]` and `[browse]` tables. We add a top-level `[names]` table.
- CLI dispatch is in `src/vtextract/cli.py::run()`; `_make_transport()` is the test seam pattern. The index CLI is `src/vtextract/index/cli.py`; the facade is `src/vtextract/index/service.py`.
- `vtextract.schema.normalize_reference_code(code)` normalizes ` `/`/` → `-`.

**Conventions:** TDD (write failing test, see it fail, implement, see it pass, commit). `uv run pytest` only, fixtures only, never a live LLM/network. Conventional commits. Every source file starts with the two-line copyright header used across the repo:
```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved
```

---

## Task 1: Add dependencies (litellm, pydantic)

**Files:**
- Modify: `pyproject.toml:8`

- [ ] **Step 1: Add the runtime deps**

In `pyproject.toml`, change the `dependencies` line to add `litellm` and `pydantic`:

```toml
dependencies = ["httpx>=0.27", "rich>=13", "textual>=0.50", "textual-image[textual]>=0.11,<0.13", "litellm>=1.40", "pydantic>=2"]
```

- [ ] **Step 2: Sync and verify import**

Run: `uv sync --extra dev && uv run python -c "import litellm, pydantic; print('ok')"`
Expected: prints `ok` (litellm may print a one-time banner; that's fine).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add litellm and pydantic deps for person-NER"
```

---

## Task 2: `names` package — models

**Files:**
- Create: `src/vtextract/names/__init__.py`
- Create: `src/vtextract/names/models.py`
- Create: `tests/names/__init__.py`
- Test: `tests/names/test_models.py`

- [ ] **Step 1: Create the test package init**

Create `tests/names/__init__.py` as an empty file (one trailing newline).

- [ ] **Step 2: Create the package init**

Create `src/vtextract/names/__init__.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved
```

- [ ] **Step 3: Write the failing test**

Create `tests/names/test_models.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.names.models import (
    Alias,
    NameResponse,
    NamesStats,
    Person,
    confidence_rank,
    meets_threshold,
)


def test_person_defaults_and_aliases():
    p = Person(canonical="William Young", aliases=[{"text": "Wm Young", "confidence": "high"}])
    assert p.confidence == "medium"  # default
    assert p.aliases[0].text == "Wm Young"
    assert isinstance(p.aliases[0], Alias)


def test_name_response_empty_default():
    assert NameResponse().people == []


def test_name_response_parse_full():
    r = NameResponse.model_validate(
        {"people": [{"canonical": "John Young", "confidence": "high",
                     "aliases": [{"text": "J. Young", "confidence": "low"}]}]}
    )
    assert r.people[0].canonical == "John Young"
    assert r.people[0].aliases[0].confidence == "low"


def test_bad_confidence_rejected():
    with pytest.raises(ValueError):
        Person(canonical="X", confidence="certain")


def test_confidence_rank_and_threshold():
    assert confidence_rank("low") < confidence_rank("high")
    assert meets_threshold("high", "medium") is True
    assert meets_threshold("low", "medium") is False
    assert meets_threshold("low", None) is True


def test_names_stats_defaults():
    s = NamesStats()
    assert (s.extracted, s.skipped, s.failed, s.people) == (0, 0, 0, 0)
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest tests/names/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.names.models'`.

- [ ] **Step 5: Implement the models**

Create `src/vtextract/names/models.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

Confidence = Literal["low", "medium", "high"]
CONFIDENCE_LEVELS: tuple[str, ...] = ("low", "medium", "high")

# On-disk sidecar format version. Bump if the sidecar JSON shape changes.
SIDECAR_SCHEMA = 1


def confidence_rank(level: str) -> int:
    return CONFIDENCE_LEVELS.index(level)


def meets_threshold(level: str, threshold: str | None) -> bool:
    if threshold is None:
        return True
    return confidence_rank(level) >= confidence_rank(threshold)


class Alias(BaseModel):
    text: str
    confidence: Confidence = "medium"


class Person(BaseModel):
    canonical: str
    confidence: Confidence = "medium"
    aliases: list[Alias] = []


class NameResponse(BaseModel):
    """The shape the LLM must return for one chunk of text."""

    people: list[Person] = []


@dataclass
class NamesStats:
    extracted: int = 0   # pages a fresh sidecar was written for
    skipped: int = 0     # pages skipped (sidecar already present)
    failed: int = 0      # pages whose extraction failed (no sidecar written)
    people: int = 0      # total Person entries written across all sidecars
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/names/test_models.py -q`
Expected: PASS (6 passed).

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/names/__init__.py src/vtextract/names/models.py tests/names/__init__.py tests/names/test_models.py
git commit -m "feat(names): person/alias/response models for NER sidecars"
```

---

## Task 3: `names` package — chunking

**Files:**
- Create: `src/vtextract/names/chunking.py`
- Test: `tests/names/test_chunking.py`

- [ ] **Step 1: Write the failing test**

Create `tests/names/test_chunking.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import pytest

from vtextract.names.chunking import chunk_text


def test_short_text_single_chunk():
    assert chunk_text("hello", 64000, 512) == [("hello", 0)]


def test_long_text_overlapping_windows():
    text = "abcdefghij"  # len 10
    chunks = chunk_text(text, 4, 1)
    # step = 3; windows start at 0,3,6,9
    assert chunks == [("abcd", 0), ("defg", 3), ("ghij", 6), ("j", 9)]


def test_invalid_args():
    with pytest.raises(ValueError):
        chunk_text("x", 0, 0)
    with pytest.raises(ValueError):
        chunk_text("x", 4, 4)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/names/test_chunking.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.names.chunking'`.

- [ ] **Step 3: Implement (ported verbatim from name-grep)**

Create `src/vtextract/names/chunking.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int]]:
    """Split text into overlapping windows.

    Returns a list of (window_text, start_offset). Text at or under chunk_size
    yields a single chunk. Consecutive windows overlap by `overlap` characters
    so a name spanning a boundary lands wholly inside at least one window.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    if len(text) <= chunk_size:
        return [(text, 0)]

    chunks: list[tuple[str, int]] = []
    step = chunk_size - overlap
    start = 0
    while start < len(text):
        chunks.append((text[start:start + chunk_size], start))
        if start + chunk_size >= len(text):
            break
        start += step
    return chunks
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/names/test_chunking.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/chunking.py tests/names/test_chunking.py
git commit -m "feat(names): port overlapping-window chunker"
```

---

## Task 4: `names` package — LLM wrapper (prompt, parse, find_people)

**Files:**
- Create: `src/vtextract/names/llm.py`
- Test: `tests/names/test_llm.py`

- [ ] **Step 1: Write the failing test**

Create `tests/names/test_llm.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract.names import llm
from vtextract.names.models import Person


def test_build_messages_contains_text_and_schema():
    msgs = llm.build_messages("Wm Young paid the toll.")
    assert msgs[0]["role"] == "system"
    assert "canonical" in msgs[0]["content"]
    assert "Wm Young paid the toll." in msgs[1]["content"]


def test_parse_people():
    content = json.dumps({"people": [
        {"canonical": "William Young", "confidence": "high",
         "aliases": [{"text": "Wm Young", "confidence": "high"}]}]})
    people = llm._parse(content)
    assert people[0].canonical == "William Young"
    assert people[0].aliases[0].text == "Wm Young"


def test_parse_lenient_strips_prose():
    content = 'Here is the JSON:\n{"people": []}\nThanks!'
    assert llm._parse(content) == []


def test_find_people_uses_completion(monkeypatch):
    captured = {}

    def fake_complete(kwargs, *, max_retries=2):
        captured["model"] = kwargs["model"]
        return json.dumps({"people": [{"canonical": "John Young", "confidence": "medium",
                                       "aliases": [{"text": "Young", "confidence": "low"}]}]})

    monkeypatch.setattr(llm, "_complete", fake_complete)
    people = llm.find_people("text", model="ollama/llama3.1")
    assert captured["model"] == "ollama/llama3.1"
    assert isinstance(people[0], Person)
    assert people[0].canonical == "John Young"


def test_find_people_reprompts_on_bad_json(monkeypatch):
    calls = []

    def fake_complete(kwargs, *, max_retries=2):
        calls.append(kwargs["messages"])
        if len(calls) == 1:
            return "not json at all"
        return json.dumps({"people": []})

    monkeypatch.setattr(llm, "_complete", fake_complete)
    assert llm.find_people("text", model="m") == []
    assert len(calls) == 2  # original + one reprompt


def test_friendly_error_not_found_ollama():
    msg = llm.friendly_error(RuntimeError("model not found, try pulling"), "ollama/llama3.1", None)
    assert "ollama pull" in msg
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/names/test_llm.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.names.llm'`.

- [ ] **Step 3: Implement the LLM wrapper**

Create `src/vtextract/names/llm.py` (the person-NER + canonicalization prompt is new; the `_complete`/`friendly_error`/`check_model` plumbing follows name-grep):

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
import time

import litellm
from pydantic import ValidationError

from vtextract.names.models import NameResponse, Person

# Keep litellm from printing its banner/provider hints on every error.
litellm.suppress_debug_info = True

SYSTEM_PROMPT = """\
You are a named-entity recognition tool. Given a block of TEXT (a transcription
of a historical document), find EVERY distinct PERSON mentioned in it.

For each person, produce:
- "canonical": the person's full name in standard "First Last" form. Expand
  common abbreviated given names to their full form (Wm->William, Thos->Thomas,
  Jno->John, Geo->George, Chas->Charles, Robt->Robert, Jas->James,
  Danl->Daniel). Drop titles/ranks (Mr, Mrs, Sgt, Capt, Rev) from the canonical
  name. NEVER expand a bare initial into a guessed first name (keep "J. Young"
  as written if that is all you have).
- "aliases": every surface form of this person that literally appears in the
  TEXT (e.g. "Wm Young", "Sgt. Young", "Young"), each with its own confidence.
- "confidence": how sure you are of the canonical identity/expansion.

Collapse multiple surface forms into ONE person when you are confident they
refer to the same individual in this text (e.g. "Thomas Young" and "Sgt. Young"
mentioned together). If you are NOT confident two mentions are the same person
(e.g. two different people surnamed Young), keep them as SEPARATE entries.

Reject:
- ordinary words that merely resemble a name (e.g. the adjective "young").
- place names and organisations (people only).

Rules:
- Every "text" value must literally appear in the TEXT. Never invent a name.
- "confidence" is one of "low", "medium", "high".
- If there are no people, output {"people": []}.

Worked example —
TEXT: "Thomas Young served in the infantry. Sgt. Young was killed in November.
Later Wm Young, his brother, paid the debt. The young recruits drilled daily."
OUTPUT:
{"people":[{"canonical":"Thomas Young","confidence":"high","aliases":[{"text":"Thomas Young","confidence":"high"},{"text":"Sgt. Young","confidence":"medium"}]},{"canonical":"William Young","confidence":"high","aliases":[{"text":"Wm Young","confidence":"high"}]}]}
(The adjective "young" is omitted.)

Respond with JSON only, no prose, in exactly this form:
{"people": [{"canonical": "...", "confidence": "low|medium|high", "aliases": [{"text": "...", "confidence": "low|medium|high"}]}]}
"""

_CONNECTION_HINTS = ("connection", "refused", "max retries", "failed to connect",
                     "timed out", "timeout", "cannot connect", "connection error")
_NOT_FOUND_HINTS = ("not found", "404", "try pulling", "no such model",
                    "does not exist", "not exist")
_AUTH_HINTS = ("authenticationerror", "unauthorized", "api key", "api-key",
               "401", "403", "permission denied", "invalid key")


def friendly_error(exc: Exception, model: str, api_base: str | None) -> str:
    """Translate a litellm/transport exception into an actionable message."""
    text = str(exc).lower()
    is_ollama = model.startswith("ollama/")
    bare = model.split("/", 1)[1] if "/" in model else model

    if isinstance(exc, (json.JSONDecodeError, ValidationError)) or "expecting value" in text:
        return (f"Model '{model}' did not return valid JSON in the required "
                f"format, even after a retry. Try a different model.")
    if any(h in text for h in _NOT_FOUND_HINTS):
        if is_ollama:
            return (f"Model '{model}' is not available locally. "
                    f"Pull it first: `ollama pull {bare}`.")
        return (f"Model '{model}' was not found. Check the model name "
                f"(LiteLLM uses the provider/model form).")
    if any(h in text for h in _CONNECTION_HINTS):
        where = f" at {api_base}" if api_base else ""
        if is_ollama:
            return (f"Could not reach the Ollama server{where} for model "
                    f"'{model}'. Is it running? Start it with `ollama serve`.")
        return (f"Could not reach the LLM provider{where} for model '{model}'. "
                f"Check your network connection and any api_base setting.")
    if any(h in text for h in _AUTH_HINTS):
        provider = model.split("/", 1)[0] if "/" in model else ""
        key_hint = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(
            provider, "the provider's API key environment variable")
        return (f"Authentication failed for model '{model}'. "
                f"Set the API key in your environment (e.g. {key_hint}).")
    return f"LLM error for model '{model}': {exc}"


def check_model(model: str, api_base: str | None = None) -> str | None:
    """Preflight the model with a tiny request; None if OK, else a diagnostic."""
    kwargs: dict = {"model": model, "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1, "temperature": 0}
    if api_base:
        kwargs["api_base"] = api_base
    try:
        litellm.completion(**kwargs)
        return None
    except Exception as exc:
        return friendly_error(exc, model, api_base)


def build_messages(chunk_text: str) -> list[dict]:
    user = f'TEXT:\n"""\n{chunk_text}\n"""'
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _loads_lenient(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def _parse(content: str) -> list[Person]:
    return NameResponse.model_validate(_loads_lenient(content)).people


def _complete(kwargs: dict, *, max_retries: int = 2) -> str:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = litellm.completion(**kwargs)
            return response["choices"][0]["message"]["content"]
        except Exception as exc:  # transport / API error
            last_exc = exc
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                raise
    raise last_exc  # pragma: no cover


def find_people(chunk_text: str, model: str, api_base: str | None = None) -> list[Person]:
    """Call the LLM and return validated people for one chunk.

    Reprompts once on malformed JSON; retries with backoff on transport errors.
    """
    messages = build_messages(chunk_text)
    kwargs: dict = {"model": model, "messages": messages, "temperature": 0}
    if api_base:
        kwargs["api_base"] = api_base

    content = _complete(kwargs)
    try:
        return _parse(content)
    except (json.JSONDecodeError, ValidationError):
        repair = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content":
                "That was not valid JSON in the required schema. Respond again "
                "with ONLY the JSON object, no prose."},
        ]
        content = _complete({**kwargs, "messages": repair})
        return _parse(content)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/names/test_llm.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/llm.py tests/names/test_llm.py
git commit -m "feat(names): LLM wrapper with person-NER + canonicalization prompt"
```

---

## Task 5: `names` package — merge across chunks

**Files:**
- Create: `src/vtextract/names/merge.py`
- Test: `tests/names/test_merge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/names/test_merge.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.names.merge import merge_people
from vtextract.names.models import Person


def test_merge_collapses_same_canonical_keeping_best_confidence():
    a = [Person(canonical="William Young", confidence="low",
                aliases=[{"text": "Wm Young", "confidence": "low"}])]
    b = [Person(canonical="william young", confidence="high",
                aliases=[{"text": "Wm Young", "confidence": "high"},
                         {"text": "Young", "confidence": "medium"}])]
    merged = merge_people([a, b])
    assert len(merged) == 1
    p = merged[0]
    assert p.canonical == "William Young"   # first-seen surface form wins
    assert p.confidence == "high"           # best entry confidence
    alias = {al.text: al.confidence for al in p.aliases}
    assert alias == {"Wm Young": "high", "Young": "medium"}  # best per alias


def test_merge_keeps_distinct_people():
    a = [Person(canonical="John Young")]
    b = [Person(canonical="Thomas Young")]
    merged = merge_people([a, b])
    assert {p.canonical for p in merged} == {"John Young", "Thomas Young"}


def test_merge_empty():
    assert merge_people([]) == []
    assert merge_people([[], []]) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/names/test_merge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.names.merge'`.

- [ ] **Step 3: Implement merge**

Create `src/vtextract/names/merge.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from vtextract.names.models import Alias, Person, confidence_rank


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def merge_people(groups: list[list[Person]]) -> list[Person]:
    """Merge per-chunk people lists into one deduped list.

    People are the same when their canonical names match after whitespace/case
    normalization. The first-seen canonical surface form is kept; the entry
    confidence becomes the best (highest) seen; aliases are unioned by
    normalized text, each keeping its highest confidence. First-seen order is
    preserved for both people and aliases.
    """
    by_key: dict[str, Person] = {}
    alias_order: dict[str, list[str]] = {}
    alias_best: dict[str, dict[str, Alias]] = {}
    order: list[str] = []

    for group in groups:
        for person in group:
            key = _norm(person.canonical)
            if key not in by_key:
                by_key[key] = Person(canonical=person.canonical, confidence=person.confidence)
                alias_order[key] = []
                alias_best[key] = {}
                order.append(key)
            else:
                existing = by_key[key]
                if confidence_rank(person.confidence) > confidence_rank(existing.confidence):
                    existing.confidence = person.confidence
            for al in person.aliases:
                ak = _norm(al.text)
                cur = alias_best[key].get(ak)
                if cur is None:
                    alias_best[key][ak] = Alias(text=al.text, confidence=al.confidence)
                    alias_order[key].append(ak)
                elif confidence_rank(al.confidence) > confidence_rank(cur.confidence):
                    cur.confidence = al.confidence

    result: list[Person] = []
    for key in order:
        person = by_key[key]
        person.aliases = [alias_best[key][ak] for ak in alias_order[key]]
        result.append(person)
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/names/test_merge.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/merge.py tests/names/test_merge.py
git commit -m "feat(names): merge per-chunk people lists, dedupe canonical + aliases"
```

---

## Task 6: `names` package — extractor (walk pages, write sidecars, resume)

**Files:**
- Create: `src/vtextract/names/extractor.py`
- Test: `tests/names/test_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/names/test_extractor.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract.names.extractor import extract, sidecar_for, page_transcriptions
from vtextract.names.models import Person


def _make_archive(tmp_path):
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "b.jpg.txt").write_text("nothing here")
    return tmp_path


def _fake_find_factory(mapping):
    # mapping: chunk substring -> people list
    def find(chunk_text, model, api_base=None):
        for needle, people in mapping.items():
            if needle in chunk_text:
                return people
        return []
    return find


def test_page_transcriptions_lists_pages(tmp_path):
    archive = _make_archive(tmp_path)
    found = {(r, k) for r, k, _ in page_transcriptions(archive)}
    assert found == {("100", "a.jpg"), ("100", "b.jpg")}


def test_sidecar_for_replaces_suffix(tmp_path):
    txt = tmp_path / "x.jpg.txt"
    assert sidecar_for(txt).name == "x.jpg.names.json"


def test_extract_writes_sidecars(tmp_path):
    archive = _make_archive(tmp_path)
    find = _fake_find_factory({"Wm Young": [Person(canonical="William Young",
                                                   aliases=[{"text": "Wm Young", "confidence": "high"}])]})
    stats = extract(archive, model="m", find=find, show_progress=False)
    assert stats.extracted == 2 and stats.skipped == 0 and stats.failed == 0
    assert stats.people == 1
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["schema"] == 1 and side["model"] == "m"
    assert side["people"][0]["canonical"] == "William Young"
    empty = json.loads((archive / "pages" / "100" / "b.jpg.names.json").read_text())
    assert empty["people"] == []


def test_extract_resumes_skipping_existing(tmp_path):
    archive = _make_archive(tmp_path)
    find = _fake_find_factory({})
    extract(archive, model="m", find=find, show_progress=False)
    # second run: all sidecars present -> all skipped
    stats = extract(archive, model="m", find=find, show_progress=False)
    assert stats.skipped == 2 and stats.extracted == 0


def test_extract_force_overwrites(tmp_path):
    archive = _make_archive(tmp_path)
    extract(archive, model="m", find=_fake_find_factory({}), show_progress=False)
    stats = extract(archive, model="m", find=_fake_find_factory({}), force=True, show_progress=False)
    assert stats.extracted == 2 and stats.skipped == 0


def test_extract_failure_leaves_no_sidecar(tmp_path):
    archive = _make_archive(tmp_path)

    def boom(chunk_text, model, api_base=None):
        raise RuntimeError("model down")

    stats = extract(archive, model="m", find=boom, show_progress=False)
    assert stats.failed == 2 and stats.extracted == 0
    assert not (archive / "pages" / "100" / "a.jpg.names.json").exists()


def test_extract_scope_limits_pages(tmp_path):
    archive = _make_archive(tmp_path)
    stats = extract(archive, model="m", find=_fake_find_factory({}),
                    scope_pages={("100", "a.jpg")}, show_progress=False)
    assert stats.extracted == 1
    assert (archive / "pages" / "100" / "a.jpg.names.json").exists()
    assert not (archive / "pages" / "100" / "b.jpg.names.json").exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/names/test_extractor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.names.extractor'`.

- [ ] **Step 3: Implement the extractor**

Create `src/vtextract/names/extractor.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.progress import Progress

from vtextract.names import llm as llm_module
from vtextract.names.chunking import chunk_text
from vtextract.names.merge import merge_people
from vtextract.names.models import SIDECAR_SCHEMA, NamesStats, Person

# (chunk_text, model, api_base) -> people for that chunk.
FindFn = Callable[[str, str, "str | None"], "list[Person]"]

_TXT_SUFFIX = ".txt"
_SIDECAR_SUFFIX = ".names.json"


def page_transcriptions(archive: Path) -> list[tuple[str, str, Path]]:
    """Return (root_id, page_key, txt_path) for every page transcription.

    page_key keeps its trailing .jpg (the file is <page_key>.txt).
    """
    out: list[tuple[str, str, Path]] = []
    pages_dir = Path(archive) / "pages"
    if not pages_dir.is_dir():
        return out
    for txt in sorted(pages_dir.glob("*/*.jpg.txt")):
        root_id = txt.parent.name
        page_key = txt.name[: -len(_TXT_SUFFIX)]
        out.append((root_id, page_key, txt))
    return out


def sidecar_for(txt_path: Path) -> Path:
    """Map <page_key>.txt -> <page_key>.names.json (same directory)."""
    txt_path = Path(txt_path)
    return txt_path.with_name(txt_path.name[: -len(_TXT_SUFFIX)] + _SIDECAR_SUFFIX)


def _write_sidecar_atomic(path: Path, model: str, people: list[Person]) -> None:
    data = {
        "schema": SIDECAR_SCHEMA,
        "model": model,
        "people": [p.model_dump() for p in people],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _extract_one(
    txt_path: Path, *, model: str, api_base: str | None,
    chunk_size: int, overlap: int, find: FindFn,
) -> list[Person]:
    """Extract people for one page. Raises if every chunk failed."""
    text = txt_path.read_text()
    groups: list[list[Person]] = []
    errors = 0
    successes = 0
    for window, _offset in chunk_text(text, chunk_size, overlap):
        try:
            groups.append(find(window, model, api_base))
            successes += 1
        except Exception:
            errors += 1
    if successes == 0 and errors > 0:
        raise RuntimeError(f"all {errors} chunk(s) failed for {txt_path}")
    return merge_people(groups)


def extract(
    archive: Path,
    *,
    model: str,
    api_base: str | None = None,
    chunk_size: int = 64000,
    overlap: int = 512,
    workers: int = 1,
    find: FindFn | None = None,
    force: bool = False,
    scope_pages: set[tuple[str, str]] | None = None,
    show_progress: bool = True,
) -> NamesStats:
    """Walk page transcriptions, extract people, write/refresh sidecars.

    Skips pages whose sidecar already exists unless ``force``. ``scope_pages``,
    when given, limits work to those (root_id, page_key) pairs. A page whose
    extraction fails is left without a sidecar so a later run retries it.
    """
    find = find or llm_module.find_people
    archive = Path(archive)
    stats = NamesStats()

    todo: list[tuple[str, Path]] = []  # (page_key, txt_path) — root_id unused downstream
    for root_id, page_key, txt in page_transcriptions(archive):
        if scope_pages is not None and (root_id, page_key) not in scope_pages:
            continue
        side = sidecar_for(txt)
        if side.exists() and not force:
            stats.skipped += 1
            continue
        todo.append((page_key, txt))

    def work(txt: Path) -> tuple[Path, list[Person] | None]:
        try:
            return txt, _extract_one(
                txt, model=model, api_base=api_base,
                chunk_size=chunk_size, overlap=overlap, find=find)
        except Exception:
            return txt, None

    def run(progress: Progress | None, task_id) -> None:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futures = [ex.submit(work, txt) for _key, txt in todo]
            for fut in as_completed(futures):
                txt, people = fut.result()
                if people is None:
                    stats.failed += 1
                else:
                    _write_sidecar_atomic(sidecar_for(txt), model, people)
                    stats.extracted += 1
                    stats.people += len(people)
                if progress is not None:
                    progress.advance(task_id)

    if show_progress and todo:
        with Progress(console=Console(stderr=True)) as progress:
            task_id = progress.add_task("Extracting names", total=len(todo))
            run(progress, task_id)
    else:
        run(None, None)
    return stats
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/names/test_extractor.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/names/extractor.py tests/names/test_extractor.py
git commit -m "feat(names): extractor walks pages, writes resumable sidecars"
```

---

## Task 7: Config — `[names]` section

**Files:**
- Modify: `src/vtextract/config.py:26-35` (Config dataclass) and `:52-78` (load_config)
- Test: `tests/test_config.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (append at end of file):

```python
def test_names_defaults_when_absent(tmp_path):
    from vtextract.config import load_config
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.names.model == "ollama/llama3.1"
    assert cfg.names.api_base is None
    assert cfg.names.chunk_size == 64000
    assert cfg.names.workers == 1


def test_names_section_parsed(tmp_path):
    from vtextract.config import load_config
    p = tmp_path / "vt.toml"
    p.write_text(
        '[names]\n'
        'model = "anthropic/claude-haiku-4-5"\n'
        'api_base = "http://localhost:11434"\n'
        'chunk_size = 8000\n'
        'workers = 4\n'
    )
    cfg = load_config(p)
    assert cfg.names.model == "anthropic/claude-haiku-4-5"
    assert cfg.names.api_base == "http://localhost:11434"
    assert cfg.names.chunk_size == 8000
    assert cfg.names.workers == 4
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_config.py -q -k names`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'names'`.

- [ ] **Step 3: Implement**

In `src/vtextract/config.py`, add a `NamesConfig` dataclass and constants above `Config` (after the existing `DEFAULT_*` constants, around line 18):

```python
DEFAULT_NAMES_MODEL = "ollama/llama3.1"


@dataclass
class NamesConfig:
    model: str = DEFAULT_NAMES_MODEL
    api_base: str | None = None
    chunk_size: int = 64000
    overlap: int = 512
    workers: int = 1
    confidence: str | None = None
```

Add a field to the `Config` dataclass (after `browse_theme`):

```python
    names: NamesConfig = field(default_factory=NamesConfig)
```

In `load_config`, after `browse = data.get("browse", {})`, build the names config and pass it to `Config(...)`:

```python
    names = data.get("names", {})
```

and add to the `Config(...)` constructor call:

```python
        names=NamesConfig(
            model=names.get("model", DEFAULT_NAMES_MODEL),
            api_base=names.get("api_base"),
            chunk_size=int(names.get("chunk_size", 64000)),
            overlap=int(names.get("overlap", 512)),
            workers=int(names.get("workers", 1)),
            confidence=names.get("confidence"),
        ),
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS (all config tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/config.py tests/test_config.py
git commit -m "feat(config): parse [names] LLM settings"
```

---

## Task 8: CLI — `vtextract names` subcommand

**Files:**
- Modify: `src/vtextract/cli.py` (add `_make_find`, `_run_names`, dispatch in `run()`, `_USAGE`)
- Test: `tests/test_cli_names.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_names.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

import json

import pytest

from vtextract import cli
from vtextract.names.models import Person


def _archive_with_page(tmp_path):
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    cfg = tmp_path / "vt.toml"
    cfg.write_text('[names]\nmodel = "test/model"\n')
    return tmp_path, cfg


def test_names_command_writes_sidecar(tmp_path, monkeypatch):
    archive, cfg = _archive_with_page(tmp_path)

    def fake_find(chunk_text, model, api_base=None):
        assert model == "test/model"
        return [Person(canonical="William Young",
                       aliases=[{"text": "Wm Young", "confidence": "high"}])]

    monkeypatch.setattr(cli, "_make_find", lambda: fake_find)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg)])
    assert rc == 0
    side = json.loads((archive / "pages" / "100" / "a.jpg.names.json").read_text())
    assert side["people"][0]["canonical"] == "William Young"


def test_names_command_model_override(tmp_path, monkeypatch):
    archive, cfg = _archive_with_page(tmp_path)
    seen = {}

    def fake_find(chunk_text, model, api_base=None):
        seen["model"] = model
        return []

    monkeypatch.setattr(cli, "_make_find", lambda: fake_find)
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg),
                  "--model", "ollama/llama3.1"])
    assert rc == 0
    assert seen["model"] == "ollama/llama3.1"


def test_names_command_no_pages_returns_zero(tmp_path, monkeypatch):
    archive = tmp_path
    (archive / "pages").mkdir()
    cfg = tmp_path / "vt.toml"
    cfg.write_text("")
    monkeypatch.setattr(cli, "_make_find", lambda: (lambda *a, **k: []))
    rc = cli.run(["names", "--archive", str(archive), "--config", str(cfg)])
    assert rc == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_cli_names.py -q`
Expected: FAIL — `AttributeError: module 'vtextract.cli' has no attribute '_make_find'` (and unknown command `names`).

- [ ] **Step 3: Implement the seam, dispatch, and handler**

In `src/vtextract/cli.py`, add the test seam next to `_make_transport` (after line 26):

```python
def _make_find():
    """Seam for tests to inject a fake find_people. Returns None in production."""
    return None
```

Add `names` to the dispatch in `run()` (after the `refresh` branch, before the unknown-command print):

```python
    if command == "names":
        return _run_names(rest)
```

Add `names` to `_USAGE` (insert a line in the commands block):

```
  names    extract people from transcriptions into per-page sidecars (LLM)
```

Add the handler function (place it after `_run_refresh`):

```python
def _run_names(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="vtextract names",
        description="Extract people from page transcriptions into per-page "
        "'.names.json' sidecars using an LLM. Resumable: skips pages that "
        "already have a sidecar (use --force to re-extract).",
    )
    parser.add_argument(
        "identifiers", nargs="*",
        help="Optional reference codes and/or isadgIDs to scope the run to "
        "those resources' pages (default: the whole archive).",
    )
    parser.add_argument("--archive", help="Archive dir (defaults to the config file's archive).")
    parser.add_argument("--config", help="Config file path (default ~/.vt/vt.toml).")
    parser.add_argument("--model", help="LiteLLM model name (overrides [names].model).")
    parser.add_argument("-w", "--workers", type=_positive_int,
                        help="Parallel workers (overrides [names].workers).")
    parser.add_argument("--force", action="store_true",
                        help="Re-extract and overwrite existing sidecars.")
    args = parser.parse_args(argv)

    config = load_config(Path(args.config) if args.config else None)
    archive = Path(args.archive) if args.archive else config.archive
    if not (archive / "pages").is_dir():
        print(f"no pages to process in {archive}", file=sys.stderr)
        return 0

    scope_pages = (
        names_extractor.pages_for_resources(archive, args.identifiers)
        if args.identifiers else None
    )
    if args.identifiers and not scope_pages:
        print("no archived pages match the given identifiers", file=sys.stderr)
        return 0

    model = args.model or config.names.model
    workers = args.workers or config.names.workers
    stats = names_extractor.extract(
        archive, model=model, api_base=config.names.api_base,
        chunk_size=config.names.chunk_size, overlap=config.names.overlap,
        workers=workers, find=_make_find(), force=args.force,
        scope_pages=scope_pages,
    )
    print(
        f"names: {stats.extracted} extracted, {stats.skipped} skipped, "
        f"{stats.failed} failed ({stats.people} people). "
        f"Run `vtindex build --archive {archive}` to index them.",
        file=sys.stderr,
    )
    return 1 if stats.failed else 0
```

Add the import near the other vtextract imports at the top of `cli.py`:

```python
from vtextract.names import extractor as names_extractor
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_cli_names.py -q`
Expected: FAIL — `AttributeError: module 'vtextract.names.extractor' has no attribute 'pages_for_resources'`. (We add it next; the seam/dispatch are now in place.)

- [ ] **Step 5: Add `pages_for_resources` to the extractor**

In `src/vtextract/names/extractor.py`, add this function (and the import at top: `from vtextract.schema import normalize_reference_code`):

```python
def pages_for_resources(archive: Path, identifiers: list[str]) -> set[tuple[str, str]]:
    """Resolve item identifiers (isadgIDs or reference codes) to their pages.

    Returns the set of (root_id, page_key) referenced by the matching items'
    metadata.json. Unknown identifiers contribute nothing.
    """
    want_ids = {tok for tok in identifiers if tok.isdigit()}
    want_codes = {normalize_reference_code(tok) for tok in identifiers if not tok.isdigit()}
    pages: set[tuple[str, str]] = set()
    items_dir = Path(archive) / "items"
    if not items_dir.is_dir():
        return pages
    for meta in items_dir.glob("*/metadata.json"):
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        rid = str(data.get("isadgID"))
        rc = normalize_reference_code(data.get("referenceCode") or "")
        if rid in want_ids or meta.parent.name in want_ids or (rc and rc in want_codes):
            for p in data.get("pages") or []:
                pages.add((str(p["root_id"]), p["page_key"]))
    return pages
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_cli_names.py tests/names/ -q`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add src/vtextract/cli.py src/vtextract/names/extractor.py tests/test_cli_names.py
git commit -m "feat(cli): vtextract names subcommand"
```

---

## Task 9: Index reader — `read_names`

**Files:**
- Modify: `src/vtextract/index/models.py` (add `PersonAliasRow`, `PersonRow`)
- Modify: `src/vtextract/index/reader.py` (add `read_names`)
- Test: `tests/index/test_reader.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/index/test_reader.py`:

```python
def test_read_names(tmp_path):
    from vtextract.index.reader import read_names
    side = tmp_path / "a.jpg.names.json"
    side.write_text(
        '{"schema": 1, "model": "m", "people": ['
        '{"canonical": "William Young", "confidence": "high",'
        ' "aliases": [{"text": "Wm Young", "confidence": "high"},'
        '             {"text": "Young", "confidence": "low"}]}]}'
    )
    people = read_names(side)
    assert len(people) == 1
    assert people[0].canonical == "William Young"
    assert people[0].confidence == "high"
    assert people[0].aliases == [("Wm Young", "high"), ("Young", "low")]


def test_read_names_empty(tmp_path):
    from vtextract.index.reader import read_names
    side = tmp_path / "b.jpg.names.json"
    side.write_text('{"schema": 1, "model": "m", "people": []}')
    assert read_names(side) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/index/test_reader.py -q -k names`
Expected: FAIL — `ImportError: cannot import name 'read_names'`.

- [ ] **Step 3: Add the models**

In `src/vtextract/index/models.py`, add (after `PageLink`):

```python
@dataclass
class PersonRow:
    """A person extracted from one page's names sidecar, flattened for indexing."""

    canonical: str
    confidence: str
    aliases: list[tuple[str, str]] = field(default_factory=list)  # (text, confidence)
```

- [ ] **Step 4: Implement `read_names`**

In `src/vtextract/index/reader.py`, add the import and function:

```python
from vtextract.index.models import ItemRow, PageFiles, PageLink, PersonRow, VolumePage, VolumeRow
```

```python
def read_names(sidecar_path: Path) -> list[PersonRow]:
    """Parse a pages/<root_id>/<page_key>.names.json sidecar into PersonRows."""
    data = json.loads(Path(sidecar_path).read_text())
    rows: list[PersonRow] = []
    for person in data.get("people") or []:
        aliases = [
            (a["text"], a.get("confidence", "medium"))
            for a in person.get("aliases") or []
        ]
        rows.append(PersonRow(
            canonical=person["canonical"],
            confidence=person.get("confidence", "medium"),
            aliases=aliases,
        ))
    return rows
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/index/test_reader.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/index/models.py src/vtextract/index/reader.py tests/index/test_reader.py
git commit -m "feat(index): read_names parses person sidecars"
```

---

## Task 10: Index DB — person tables, upsert, delete, FTS search

**Files:**
- Modify: `src/vtextract/index/db.py` (bump `SCHEMA_VERSION`, extend `_DDL`, add upsert/delete/search/count)
- Test: `tests/index/test_db_write.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/index/test_db_write.py`:

```python
def test_person_upsert_and_fts_search(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    rows = [PersonRow(canonical="William Young", confidence="high",
                      aliases=[("Wm Young", "high"), ("Young", "low")])]
    db.upsert_names("100", "a.jpg", rows, fingerprint=("pages/100/a.jpg.names.json", 1.0, 10))
    hits = db.person_fts_search("Wm Young")
    assert len(hits) == 1
    assert hits[0]["canonical"] == "William Young"
    assert (hits[0]["root_id"], hits[0]["page_key"]) == ("100", "a.jpg")
    # alias text is searchable too
    assert db.person_fts_search("Young")
    assert db.counts()["people"] == 1
    db.close()


def test_person_reupsert_replaces_page(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    fp = ("pages/100/a.jpg.names.json", 1.0, 10)
    db.upsert_names("100", "a.jpg", [PersonRow("John Young", "high")], fingerprint=fp)
    db.upsert_names("100", "a.jpg", [PersonRow("Thomas Young", "high")], fingerprint=fp)
    names = {h["canonical"] for h in db.person_fts_search("Young")}
    assert names == {"Thomas Young"}  # old row replaced
    db.close()


def test_delete_source_names(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    rel = "pages/100/a.jpg.names.json"
    db.upsert_names("100", "a.jpg", [PersonRow("John Young", "high")], fingerprint=(rel, 1.0, 10))
    db.delete_source(rel)
    assert db.person_fts_search("Young") == []
    assert db.counts()["people"] == 0
    db.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/index/test_db_write.py -q -k person`
Expected: FAIL — `AttributeError: 'IndexDB' object has no attribute 'upsert_names'`.

- [ ] **Step 3: Implement**

In `src/vtextract/index/db.py`:

(a) Bump the schema version (line 11):

```python
SCHEMA_VERSION = 4
```

(b) Extend `_DDL` — add these tables before the closing `"""` (after the `transcription_fts` line):

```sql
CREATE TABLE person (
    id INTEGER PRIMARY KEY,
    canonical TEXT, root_id TEXT, page_key TEXT, confidence TEXT
);
CREATE TABLE person_alias (
    person_id INTEGER, text TEXT, confidence TEXT
);
CREATE INDEX ix_person_page ON person (root_id, page_key);
CREATE INDEX ix_person_alias_pid ON person_alias (person_id);
CREATE VIRTUAL TABLE person_fts USING fts5(text);
CREATE TABLE person_fts_map (rowid INTEGER PRIMARY KEY, person_id INTEGER);
```

(c) Add upsert/delete methods (place after `_delete_page_fts`, before `delete_source`):

```python
    # --- person (names sidecar) upsert / delete ---

    def upsert_names(
        self, root_id: str, page_key: str, people, *, fingerprint: tuple[str, float, int]
    ) -> None:
        path, mtime, size = fingerprint
        self._delete_person_rows(root_id, page_key)
        for person in people:
            cur = self._conn.execute(
                "INSERT INTO person (canonical, root_id, page_key, confidence) "
                "VALUES (?, ?, ?, ?)",
                (person.canonical, root_id, page_key, person.confidence),
            )
            person_id = cur.lastrowid
            for text, confidence in person.aliases:
                self._conn.execute(
                    "INSERT INTO person_alias (person_id, text, confidence) VALUES (?, ?, ?)",
                    (person_id, text, confidence),
                )
            # One FTS row per person: canonical plus every alias surface form, so
            # any written form matches and results resolve back to the canonical.
            fts_text = " ".join([person.canonical] + [t for t, _c in person.aliases])
            fcur = self._conn.execute("INSERT INTO person_fts (text) VALUES (?)", (fts_text,))
            self._conn.execute(
                "INSERT INTO person_fts_map (rowid, person_id) VALUES (?, ?)",
                (fcur.lastrowid, person_id),
            )
        self._set_fingerprint(path, "names", mtime, size)

    def _delete_person_rows(self, root_id: str, page_key: str) -> None:
        ids = [
            r["id"] for r in self._conn.execute(
                "SELECT id FROM person WHERE root_id=? AND page_key=?", (root_id, page_key))
        ]
        for pid in ids:
            for fr in self._conn.execute(
                "SELECT rowid FROM person_fts_map WHERE person_id=?", (pid,)
            ):
                self._conn.execute("DELETE FROM person_fts WHERE rowid=?", (fr["rowid"],))
            self._conn.execute("DELETE FROM person_fts_map WHERE person_id=?", (pid,))
            self._conn.execute("DELETE FROM person_alias WHERE person_id=?", (pid,))
        self._conn.execute("DELETE FROM person WHERE root_id=? AND page_key=?", (root_id, page_key))
```

(d) Handle the `"names"` kind in `delete_source` — add this branch alongside the existing `kind == ...` branches (before the final `DELETE FROM source_file`):

```python
        elif kind == "names":
            # path = pages/<root_id>/<page_key>.names.json
            parts = path.split("/")
            root_id = parts[1]
            page_key = parts[2][: -len(".names.json")]
            self._delete_person_rows(root_id, page_key)
```

(e) Add the search primitive (place near `transcription_fts_search`):

```python
    def person_fts_search(self, text: str) -> list[dict]:
        """Return [{person_id, root_id, page_key, canonical, confidence, score}]
        for person FTS matches over canonical + alias text."""
        query = fts_query(text)
        if not query:
            return []
        rows = self._conn.execute(
            "SELECT p.id AS person_id, p.root_id AS root_id, p.page_key AS page_key, "
            "p.canonical AS canonical, p.confidence AS confidence, "
            "bm25(person_fts) AS score FROM person_fts "
            "JOIN person_fts_map m ON m.rowid = person_fts.rowid "
            "JOIN person p ON p.id = m.person_id "
            "WHERE person_fts MATCH ?",
            (query,),
        )
        return [dict(r) for r in rows]
```

(f) Add `people` to `counts()` — extend the `names` list and the `plural` map:

```python
        names = ["item", "volume", "page", "item_volume", "item_page", "source_file", "person"]
        plural = {"item": "items", "volume": "volumes", "page": "pages",
                  "source_file": "source_files", "person": "people"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/index/test_db_write.py -q`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Verify the schema-bump test still guards correctly**

Run: `uv run pytest tests/index/test_db_schema.py -q`
Expected: PASS. If a test asserts the literal `SCHEMA_VERSION == 3`, update it to `4` (this is an intentional bump). If it asserts a stored-version mismatch raises `SchemaMismatch`, it should still pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/vtextract/index/db.py tests/index/test_db_write.py tests/index/test_db_schema.py
git commit -m "feat(index): person/alias tables, FTS search, schema v4"
```

---

## Task 11: Index builder — ingest sidecars

**Files:**
- Modify: `src/vtextract/index/builder.py` (`_candidates`, `_index_one`)
- Test: `tests/index/test_builder.py` (add case)

- [ ] **Step 1: Write the failing test**

Add to `tests/index/test_builder.py`:

```python
def test_build_ingests_names_sidecar(tmp_path):
    from vtextract.index.builder import build, INDEX_RELPATH
    from vtextract.index.db import IndexDB
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "a.jpg.names.json").write_text(
        '{"schema":1,"model":"m","people":[{"canonical":"William Young",'
        '"confidence":"high","aliases":[{"text":"Wm Young","confidence":"high"}]}]}'
    )
    stats = build(tmp_path)
    assert stats.added >= 1
    db = IndexDB(tmp_path / INDEX_RELPATH)
    assert db.person_fts_search("Young")[0]["canonical"] == "William Young"
    db.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/index/test_builder.py -q -k names`
Expected: FAIL — the sidecar is not enumerated, so `person_fts_search` returns `[]` and indexing raises `IndexError`.

- [ ] **Step 3: Implement**

In `src/vtextract/index/builder.py`:

(a) Add the sidecar glob in `_candidates` (inside the `pages_dir.is_dir()` block, after the transcription glob):

```python
        for side in sorted(pages_dir.glob("*/*.jpg.names.json")):
            out.append(("names", f"pages/{side.parent.name}/{side.name}", side))
```

(b) Update the import line:

```python
from vtextract.index.reader import read_item, read_names, read_transcription, read_volume
```

(c) Add the `names` branch in `_index_one` (after the `transcription` branch):

```python
    elif kind == "names":
        root_id = abspath.parent.name
        page_key = abspath.name[: -len(".names.json")]  # page_key keeps .jpg
        db.upsert_names(root_id, page_key, read_names(abspath), fingerprint=fp)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/index/test_builder.py -q`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/builder.py tests/index/test_builder.py
git commit -m "feat(index): builder ingests names sidecars"
```

---

## Task 12: Query + service — people lookup

**Files:**
- Modify: `src/vtextract/index/models.py` (add `PersonHit`)
- Create: `src/vtextract/index/people.py` (query composition)
- Modify: `src/vtextract/index/service.py` (add `people()`)
- Test: `tests/index/test_query.py` (add cases), `tests/index/test_service.py` (add case)

- [ ] **Step 1: Write the failing test (query)**

Add to `tests/index/test_query.py`:

```python
def _people_db(tmp_path):
    from vtextract.index.db import IndexDB
    from vtextract.index.models import PersonRow
    db = IndexDB(tmp_path / "i.sqlite3", rebuild=True)
    # two people on one page; link the page to an item
    db.upsert_names("100", "a.jpg",
                    [PersonRow("William Young", "high", [("Wm Young", "high")]),
                     PersonRow("Thomas Young", "low")],
                    fingerprint=("pages/100/a.jpg.names.json", 1.0, 10))
    db._conn.execute(
        "INSERT INTO item_page (isadg_id, root_id, page_key, role) VALUES (?, ?, ?, ?)",
        (42, "100", "a.jpg", "primary"))
    db.commit()
    return db


def test_people_search_maps_to_items(tmp_path):
    from vtextract.index.people import people_search
    db = _people_db(tmp_path)
    hits = people_search(db, "Young", confidence=None)
    canon = {h.canonical: h for h in hits}
    assert set(canon) == {"William Young", "Thomas Young"}
    assert canon["William Young"].items == [42]
    assert (canon["William Young"].root_id, canon["William Young"].page_key) == ("100", "a.jpg")
    db.close()


def test_people_search_confidence_filter(tmp_path):
    from vtextract.index.people import people_search
    db = _people_db(tmp_path)
    hits = people_search(db, "Young", confidence="medium")
    assert {h.canonical for h in hits} == {"William Young"}  # low-confidence dropped
    db.close()


def test_people_search_empty_query(tmp_path):
    from vtextract.index.people import people_search
    db = _people_db(tmp_path)
    assert people_search(db, "", confidence=None) == []
    db.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/index/test_query.py -q -k people`
Expected: FAIL — `ModuleNotFoundError: No module named 'vtextract.index.people'`.

- [ ] **Step 3: Add the model**

In `src/vtextract/index/models.py`, add:

```python
@dataclass
class PersonHit:
    canonical: str
    confidence: str
    root_id: str
    page_key: str
    items: list[int]   # isadg_ids referencing this page
    score: float
```

- [ ] **Step 4: Implement the query**

Create `src/vtextract/index/people.py`:

```python
# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from vtextract.index.db import IndexDB
from vtextract.index.models import PersonHit
from vtextract.names.models import meets_threshold


def people_search(db: IndexDB, name: str, *, confidence: str | None) -> list[PersonHit]:
    """Search people by name (canonical + aliases), best match first.

    ``confidence`` filters by the person's entry-level confidence at query time.
    Each hit carries the page it was found on and the items referencing that page.
    """
    if not name.strip():
        return []
    raw = db.person_fts_search(name)
    pages = sorted({(r["root_id"], r["page_key"]) for r in raw})
    items_by_page: dict[tuple[str, str], list[int]] = {}
    for isadg_id, links in db.items_for_pages(pages).items():
        for root_id, page_key, _role in links:
            items_by_page.setdefault((root_id, page_key), []).append(isadg_id)

    hits: list[PersonHit] = []
    for r in raw:
        if not meets_threshold(r["confidence"], confidence):
            continue
        page = (r["root_id"], r["page_key"])
        hits.append(PersonHit(
            canonical=r["canonical"], confidence=r["confidence"],
            root_id=r["root_id"], page_key=r["page_key"],
            items=sorted(items_by_page.get(page, [])), score=r["score"],
        ))
    hits.sort(key=lambda h: h.score)  # bm25: more negative = better
    return hits
```

- [ ] **Step 5: Run to verify the query tests pass**

Run: `uv run pytest tests/index/test_query.py -q -k people`
Expected: PASS (3 passed).

- [ ] **Step 6: Write the failing service test**

Add to `tests/index/test_service.py`:

```python
def test_service_people(tmp_path):
    from vtextract.index.builder import build
    from vtextract.index.service import IndexService
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "a.jpg.names.json").write_text(
        '{"schema":1,"model":"m","people":[{"canonical":"William Young",'
        '"confidence":"high","aliases":[{"text":"Wm Young","confidence":"high"}]}]}'
    )
    build(tmp_path)
    with IndexService(tmp_path) as svc:
        hits = svc.people("Young", confidence=None)
    assert hits[0].canonical == "William Young"
```

- [ ] **Step 7: Run it to verify it fails**

Run: `uv run pytest tests/index/test_service.py -q -k people`
Expected: FAIL — `AttributeError: 'IndexService' object has no attribute 'people'`.

- [ ] **Step 8: Implement `IndexService.people`**

In `src/vtextract/index/service.py`:

(a) Add to the model import block: `PersonHit`.
(b) Add the import: `from vtextract.index.people import people_search as _people_search`.
(c) Add the method (in the `# --- reads ---` section):

```python
    def people(self, name: str, *, confidence: str | None = None) -> list[PersonHit]:
        return _people_search(self.db, name, confidence=confidence)
```

- [ ] **Step 9: Run to verify it passes**

Run: `uv run pytest tests/index/test_query.py tests/index/test_service.py -q`
Expected: PASS (all).

- [ ] **Step 10: Commit**

```bash
git add src/vtextract/index/models.py src/vtextract/index/people.py src/vtextract/index/service.py tests/index/test_query.py tests/index/test_service.py
git commit -m "feat(index): people_search query + service.people facade"
```

---

## Task 13: vtindex CLI — `people` subcommand

**Files:**
- Modify: `src/vtextract/index/cli.py` (add `_cmd_people`, subparser)
- Test: `tests/index/test_cli.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/index/test_cli.py`:

```python
def _build_people_archive(tmp_path):
    from vtextract.index.builder import build
    pages = tmp_path / "pages" / "100"
    pages.mkdir(parents=True)
    (pages / "a.jpg.txt").write_text("Wm Young paid the toll.")
    (pages / "a.jpg.names.json").write_text(
        '{"schema":1,"model":"m","people":[{"canonical":"William Young",'
        '"confidence":"high","aliases":[{"text":"Wm Young","confidence":"high"}]}]}'
    )
    build(tmp_path)
    return tmp_path


def test_cli_people_json(tmp_path, capsys):
    from vtextract.index.cli import main
    archive = _build_people_archive(tmp_path)
    rc = main(["people", "Young", "--archive", str(archive), "--json"])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out[0]["canonical"] == "William Young"


def test_cli_people_no_match(tmp_path, capsys):
    from vtextract.index.cli import main
    archive = _build_people_archive(tmp_path)
    rc = main(["people", "Nobody", "--archive", str(archive), "--json"])
    assert rc == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/index/test_cli.py -q -k people`
Expected: FAIL — argparse exits 2 on unknown command `people` (SystemExit), or `invalid choice`.

- [ ] **Step 3: Implement**

In `src/vtextract/index/cli.py`:

(a) Add the handler (place after `_cmd_item`):

```python
def _cmd_people(args) -> int:
    archive = _resolve_archive(args)
    with IndexService(archive) as svc:
        if svc.is_stale():
            print("warning: index is stale; run `vtindex build` to refresh.",
                  file=sys.stderr)
        hits = svc.people(args.query, confidence=args.confidence)
    if args.json:
        data = [
            {"canonical": h.canonical, "confidence": h.confidence,
             "root_id": h.root_id, "page_key": h.page_key,
             "items": h.items, "score": h.score}
            for h in hits
        ]
        print(json.dumps(data, indent=2))
    else:
        _print_people_table(hits, theme=THEMES[args.theme], query=args.query)
    return 0 if hits else 1


def _print_people_table(hits, *, theme: Theme, query: str | None) -> None:
    if not hits:
        print("no matches")
        return
    table = Table(
        show_header=True,
        header_style=theme.header_style,
        border_style=theme.border_style,
        row_styles=list(theme.row_styles),
    )
    table.add_column("Person")
    table.add_column("Conf", no_wrap=True)
    table.add_column("Page", no_wrap=True)
    table.add_column("Items")
    for h in hits:
        table.add_row(
            _highlight_title(h.canonical, query, theme.match_style),
            h.confidence,
            f"{h.root_id}/{h.page_key}",
            ", ".join(str(i) for i in h.items) or "-",
        )
    Console(no_color=theme.no_color).print(table)
```

(b) Register the subparser (in `_build_parser`, after the `item` subparser, before `return parser`):

```python
    p_people = sub.add_parser("people", help="search extracted people by name")
    p_people.add_argument("query", help="person name (matches canonical + aliases)")
    _add_archive_args(p_people)
    p_people.add_argument("--confidence", choices=("low", "medium", "high"),
                          help="minimum entry confidence to include")
    p_people.add_argument("--json", action="store_true")
    _add_theme_args(p_people)
    p_people.set_defaults(func=_cmd_people)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/index/test_cli.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/vtextract/index/cli.py tests/index/test_cli.py
git commit -m "feat(index): vtindex people subcommand"
```

---

## Task 14: Docs — CLAUDE.md, README, TODO

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `TODO.md`

- [ ] **Step 1: Update CLAUDE.md**

In the architecture section, add a bullet for the new subpackage (after the `index/` bullet, before `tui/`):

```markdown
- `names/` (subpackage) — the `vtextract names` person-NER pass. **The only LLM
  call boundary** (LiteLLM via `names/llm.py`, analogous to `client.py` for
  HTTP). `extractor.py` walks `archive/pages/**/*.jpg.txt`, extracts people once
  per page (canonical name + aliases, within-page coreference + abbreviation
  expansion), and writes durable `{page_key}.names.json` sidecars (resumable;
  `--force` re-extracts). `chunking.py`/`merge.py`/`models.py` are pure helpers.
  The sidecars are the precious source data; `vtindex build` ingests them into
  the `person`/`person_alias` tables and `vtindex people "<name>"` searches them.
```

In "Running things", add under the CLI bullet:

```markdown
  A `names` command (`vtextract names [refcodes/ids...] [--archive PATH]
  [--model M] [--force]`) runs an LLM over page transcriptions to extract people
  into `.names.json` sidecars; config is `[names]` in `~/.vt/vt.toml`. Then
  `vtindex build` ingests them and `vtindex people "<name>"` searches.
```

- [ ] **Step 2: Update README.md**

Add a short "Extracting people (names)" section documenting `vtextract names`, the `[names]` config block (model/api_base/chunk_size/workers), the resumable/`--force` behaviour, and the `vtindex people "<name>" [--confidence] [--json]` query. Mirror the style/length of the existing index section.

- [ ] **Step 3: Update TODO.md**

Add a follow-ups bullet group:

```markdown
## Person-NER follow-ups
- vtbrowse (TUI) person-search pane over the index.
- Cross-page coreference (global identity resolution across the archive).
- Optional per-alias context snippets in sidecars for richer auditing.
- Places / organisations extraction (schema + command generalise).
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md TODO.md
git commit -m "docs: document vtextract names and vtindex people"
```

---

## Task 15: Full suite + boundary check

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS (all tests, including the pre-existing ones). If `tests/test_no_direct_db.py` or a TUI boundary test fails, investigate — `names/` must not be imported by `tui/`, and nothing new should import `index.db`/`query`/`builder` outside the index package except `index/people.py` (which legitimately imports `db` and `names.models`).

- [ ] **Step 2: Smoke-test the CLI help wiring**

Run: `uv run vtextract names --help` and `uv run vtindex people --help`
Expected: both print help and exit 0 (no import errors).

- [ ] **Step 3: Final commit (if any incidental fixes were needed)**

```bash
git add -A
git commit -m "test: full suite green for person-NER"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** Task 2–6 = extraction + sidecars (people-only, canonical+aliases, no context, within-page merge, resumable, atomic). Task 7–8 = `[names]` config + `vtextract names` command (whole-archive default, refcode/id scoping, `--force`, `--model`/`-w`). Task 9–11 = reader + DB tables (schema v4) + builder ingest. Task 12–13 = `people_search`/`service.people` + `vtindex people`. Task 14 = docs. TUI / cross-page / places-orgs are explicitly deferred (Task 14 TODO).
- **Boundary:** `names/llm.py` is the only module importing `litellm`. `index/people.py` imports `names.models` (pure dataclasses + pydantic; no litellm) — acceptable. `tui/` imports nothing new.
- **`page_key` handling is consistent everywhere:** files are `*.jpg.txt` / `*.jpg.names.json`; `page_key` keeps the `.jpg`; suffix-stripping uses the exact literal lengths (`.txt`, `.names.json`).
- **No live LLM/network:** every test injects a `find`/`_complete`/`_make_find` fake or monkeypatches; no test imports trigger a real `litellm.completion`.
