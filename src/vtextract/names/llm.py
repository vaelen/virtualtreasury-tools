# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

import json
import time

import httpx
import litellm
from pydantic import ValidationError

from vtextract.names.models import NameResponse, Person, Usage, sum_usage

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

# Rate-limit handling: providers cap output tokens/requests per minute, so a
# 429 needs a much longer, dedicated backoff than a transient transport blip.
_RATE_LIMIT_BASE_DELAY = 5.0   # seconds; first wait when no Retry-After header
_RATE_LIMIT_MAX_DELAY = 60.0   # cap per wait (per-minute windows reset by then)
_RATE_LIMIT_RETRIES = 6        # extra attempts reserved for rate limits
_RATE_LIMIT_HINTS = ("rate limit", "rate_limit", "too many requests",
                     "tokens per minute", "requests per minute", "429")

_CONNECTION_HINTS = ("connection", "refused", "max retries", "failed to connect",
                     "timed out", "timeout", "cannot connect", "connection error")
_NOT_FOUND_HINTS = ("not found", "404", "try pulling", "no such model",
                    "does not exist", "not exist")
_AUTH_HINTS = ("authenticationerror", "unauthorized", "api key", "api-key",
               "401", "403", "permission denied", "invalid key")

# Tuning params we send that some (newer) models reject. When a provider rejects
# one, we drop it, retry, and remember not to send it again this process -- so we
# don't pay a failed request on every later call. (Claude Opus 4.8, e.g.,
# deprecates `temperature`.)
_DROPPABLE_PARAMS = ("temperature",)
_UNSUPPORTED_PARAM_HINTS = ("deprecated", "not supported", "unsupported",
                            "not permitted", "is not allowed", "does not support",
                            "unrecognized", "unexpected keyword")

# model -> set of param names that model rejected this process.
_unsupported_params: dict[str, set[str]] = {}


def _offending_param(exc: Exception) -> str | None:
    """Name of a tuning param the model rejected, so the caller can drop it.

    Returns a param from ``_DROPPABLE_PARAMS`` only when the error reads like a
    "param X is deprecated/unsupported" complaint, else None.
    """
    text = str(exc).lower()
    if not any(h in text for h in _UNSUPPORTED_PARAM_HINTS):
        return None
    for param in _DROPPABLE_PARAMS:
        if param in text:
            return param
    return None


def _strip_unsupported(kwargs: dict) -> dict:
    """Drop params the model has already rejected once this process."""
    bad = _unsupported_params.get(kwargs.get("model"))
    if bad:
        return {k: v for k, v in kwargs.items() if k not in bad}
    return kwargs


def friendly_error(exc: Exception, model: str, api_base: str | None) -> str:
    """Translate a litellm/transport exception into an actionable message."""
    text = str(exc).lower()
    is_ollama = model.startswith("ollama/")
    bare = model.split("/", 1)[1] if "/" in model else model

    if isinstance(exc, (json.JSONDecodeError, ValidationError)) or "expecting value" in text:
        return (f"Model '{model}' did not return valid JSON in the required "
                f"format, even after a retry. Try a different model.")
    if _is_rate_limit(exc):
        return (f"Hit the provider's rate limit for model '{model}', even after "
                f"backing off and retrying. Slow down (fewer --workers) or wait "
                f"and re-run; the page is left unwritten so it retries next run.")
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
    """Preflight the model with a tiny request; None if OK, else a diagnostic.

    For a local (Ollama) model this also warms it: the tiny request loads the
    model into memory, so a caller's first real request is not paying the
    cold-start load cost.
    """
    kwargs: dict = {"model": model, "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1, "temperature": 0}
    if api_base:
        kwargs["api_base"] = api_base
    try:
        # Route through _complete so a model that rejects a tuning param (e.g.
        # Opus deprecating temperature) is recovered here, not skipped. No
        # retries: preflight should surface a real error promptly.
        _complete(kwargs, max_retries=0, rate_limit_retries=0)
        return None
    except Exception as exc:
        return friendly_error(exc, model, api_base)


_OLLAMA_DEFAULT_BASE = "http://localhost:11434"


def unload(model: str, api_base: str | None = None) -> None:
    """Best-effort: evict a loaded local (Ollama) model to free memory.

    A ``keep_alive: 0`` request makes Ollama unload the model immediately,
    easing GPU/RAM pressure before the next model loads. litellm strips Ollama's
    ``keep_alive`` param, so we call Ollama's HTTP API directly. A no-op for
    non-Ollama models. Never raises: eviction is advisory, so a failure here must
    not abort the caller's work.
    """
    if not model.startswith("ollama/"):
        return
    base = (api_base or _OLLAMA_DEFAULT_BASE).rstrip("/")
    name = model.split("/", 1)[1]  # Ollama's own API has no "ollama/" prefix
    try:
        httpx.post(f"{base}/api/generate",
                   json={"model": name, "keep_alive": 0}, timeout=30.0)
    except Exception:
        pass


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


def _is_rate_limit(exc: Exception) -> bool:
    """True if exc is a provider rate-limit (429), typed or message-only."""
    if isinstance(exc, litellm.RateLimitError):
        return True
    if getattr(exc, "status_code", None) == 429:
        return True
    return any(h in str(exc).lower() for h in _RATE_LIMIT_HINTS)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Honor a numeric Retry-After header on a rate-limit response, if present."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return float(value)  # delta-seconds form; HTTP-date form is ignored
    except (TypeError, ValueError):
        return None


def usage_from_response(response: object) -> Usage | None:
    """Extract normalized token usage from a litellm completion response.

    Returns None when the response carries no ``usage`` block (e.g. some local
    Ollama responses), so callers can tell "untracked" from a real zero. litellm
    folds Anthropic's cache_read/cache_creation into ``prompt_tokens`` and maps
    cache *reads* into ``prompt_tokens_details.cached_tokens``, so this single
    extraction is consistent across providers (cached is a subset of input).
    """
    raw = response.get("usage") if isinstance(response, dict) \
        else getattr(response, "usage", None)
    if raw is None:
        return None

    def field(obj: object, key: str, default: int = 0) -> int:
        if obj is None:
            return default
        value = obj.get(key, default) if isinstance(obj, dict) \
            else getattr(obj, key, default)
        return int(value or default)

    details = raw.get("prompt_tokens_details") if isinstance(raw, dict) \
        else getattr(raw, "prompt_tokens_details", None)
    return Usage(
        input=field(raw, "prompt_tokens"),
        output=field(raw, "completion_tokens"),
        cached=field(details, "cached_tokens"),
    )


def _complete(kwargs: dict, *, max_retries: int = 2,
              rate_limit_retries: int = _RATE_LIMIT_RETRIES) -> tuple[str, Usage | None]:
    """Call the model, retrying on transient errors.

    Rate limits (429) get their own generous budget: we wait the server's
    Retry-After if given, else an exponential backoff from
    ``_RATE_LIMIT_BASE_DELAY`` up to ``_RATE_LIMIT_MAX_DELAY``. Other transport
    errors keep the short ``2 ** attempt`` backoff. The two budgets are
    independent so a slow rate-limit recovery never burns the transport retries.
    """
    kwargs = _strip_unsupported(dict(kwargs))
    attempt = 0
    rl_attempt = 0
    while True:
        try:
            response = litellm.completion(**kwargs)
            content = response["choices"][0]["message"]["content"]
            return content, usage_from_response(response)
        except Exception as exc:  # transport / API error
            param = _offending_param(exc)
            if param and param in kwargs:
                # Model rejects this tuning param: drop it, remember for later
                # calls, and retry now (does not consume a retry budget).
                _unsupported_params.setdefault(kwargs["model"], set()).add(param)
                del kwargs[param]
                continue
            if _is_rate_limit(exc):
                if rl_attempt >= rate_limit_retries:
                    raise
                delay = _retry_after_seconds(exc)
                if delay is None:
                    delay = min(_RATE_LIMIT_BASE_DELAY * (2 ** rl_attempt),
                                _RATE_LIMIT_MAX_DELAY)
                rl_attempt += 1
                time.sleep(delay)
            else:
                if attempt >= max_retries:
                    raise
                time.sleep(2 ** attempt)
                attempt += 1


def find_people(chunk_text: str, model: str, api_base: str | None = None,
                ) -> tuple[list[Person], Usage | None]:
    """Call the LLM and return (validated people, token usage) for one chunk.

    Reprompts once on malformed JSON; retries with backoff on transport errors.
    When a reprompt is needed its tokens are billed too, so the returned usage
    sums both calls.
    """
    messages = build_messages(chunk_text)
    kwargs: dict = {"model": model, "messages": messages, "temperature": 0}
    if api_base:
        kwargs["api_base"] = api_base

    content, usage = _complete(kwargs)
    try:
        return _parse(content), usage
    except (json.JSONDecodeError, ValidationError):
        repair = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content":
                "That was not valid JSON in the required schema. Respond again "
                "with ONLY the JSON object, no prose."},
        ]
        content, repair_usage = _complete({**kwargs, "messages": repair})
        return _parse(content), sum_usage([usage, repair_usage])
