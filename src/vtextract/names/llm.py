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

# Stable substring carried in every TruncatedResponseError message. The extractor
# wraps the cause in a RuntimeError (so isinstance no longer matches by the time
# friendly_error sees it), but the message text propagates, so we classify on this.
_TRUNCATION_MARKER = "response truncated at output-token limit"

# Provider finish_reason values that mean "output cut off at the token cap".
_TRUNCATION_FINISH_REASONS = ("length", "max_tokens")

# Temperature for the JSON-repair / truncation retry. The first pass runs at 0
# (deterministic), but greedy decoding is what loops on repetitive text (e.g. will
# indexes) until the output cap. Measured on the real failing pages: temp 0.3 was
# NOT enough to escape the loop (still truncated at 65,536 tokens); 0.5 broke the
# loop on every sampled page AND kept the JSON valid, while 0.7 sometimes produced
# malformed JSON. So 0.5 is the lowest reliable, lowest-risk loop-breaker. Only the
# retry uses it, so pass-1 determinism is preserved.
_RETRY_TEMPERATURE = 0.5


class TruncatedResponseError(Exception):
    """The model's output was cut off at its token cap (finish_reason=length).

    The truncated text is incomplete JSON, so parsing it would fail with a
    misleading delimiter error. Carries the attempt's ``usage`` so the caller can
    still bill the wasted tokens when it retries.
    """

    def __init__(self, message: str, usage: "Usage | None" = None,
                 finish_reason: str | None = None) -> None:
        super().__init__(message)
        self.usage = usage
        self.finish_reason = finish_reason


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


def _provider_detail(exc: Exception) -> str:
    """The provider's own first line of explanation, trimmed for display.

    The category friendly_error picks is a heuristic over the exception text, so
    a misclassification can hide the true cause (e.g. a daily-quota cap looks
    like a generic rate limit; a 403 billing error looks like a bad key).
    Surfacing the provider's own words means the truth is never fully hidden.
    We keep only the first line -- litellm folds a full traceback into
    ``str(exc)`` -- and cap the length so a stray stack dump can't flood output.
    """
    lines = str(exc).strip().splitlines()
    first = lines[0].strip() if lines else exc.__class__.__name__
    return first[:300]


def _with_detail(label: str, exc: Exception) -> str:
    return f"{label} (provider said: {_provider_detail(exc)})"


def friendly_error(exc: Exception, model: str, api_base: str | None) -> str:
    """Translate a litellm/transport exception into an actionable message.

    Every classified branch keeps the provider's own first line appended (via
    ``_with_detail``) so a wrong guess never erases the real cause -- the JSON
    branch is the exception, since there the provider returned a 200 and the
    "detail" would just be our own parser's complaint.
    """
    text = str(exc).lower()
    is_ollama = model.startswith("ollama/")
    bare = model.split("/", 1)[1] if "/" in model else model

    if isinstance(exc, TruncatedResponseError) or _TRUNCATION_MARKER in text:
        return (f"Model '{model}' hit its output-token limit and the response was "
                f"cut off mid-JSON (typically a repetition loop on dense, "
                f"repetitive text such as a name index), even after retrying at a "
                f"higher temperature. Try a smaller chunk_size or a different model.")
    if isinstance(exc, (json.JSONDecodeError, ValidationError)) or "expecting value" in text:
        return (f"Model '{model}' did not return valid JSON in the required "
                f"format, even after a retry. Try a different model.")
    if _is_rate_limit(exc):
        return _with_detail(
            f"Hit the provider's rate limit for model '{model}', even after "
            f"backing off and retrying. Slow down (fewer --workers) or wait "
            f"and re-run; the page is left unwritten so it retries next run.", exc)
    if any(h in text for h in _NOT_FOUND_HINTS):
        if is_ollama:
            return _with_detail(
                f"Model '{model}' is not available locally. "
                f"Pull it first: `ollama pull {bare}`.", exc)
        return _with_detail(
            f"Model '{model}' was not found. Check the model name "
            f"(LiteLLM uses the provider/model form).", exc)
    # Auth before connection: LiteLLM wraps a missing/invalid key in
    # APIConnectionError, whose class name contains "connection" and would
    # otherwise be misreported as a network failure. A real key complaint always
    # names the key, so match that first.
    if any(h in text for h in _AUTH_HINTS):
        provider = model.split("/", 1)[0] if "/" in model else ""
        key_hint = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                    "gemini": "GEMINI_API_KEY", "google": "GEMINI_API_KEY",
                    "mistral": "MISTRAL_API_KEY"}.get(
            provider, "the provider's API key environment variable")
        return _with_detail(
            f"Authentication failed for model '{model}'. "
            f"Set the API key in your environment (e.g. {key_hint}).", exc)
    if any(h in text for h in _CONNECTION_HINTS):
        where = f" at {api_base}" if api_base else ""
        if is_ollama:
            return _with_detail(
                f"Could not reach the Ollama server{where} for model "
                f"'{model}'. Is it running? Start it with `ollama serve`.", exc)
        return _with_detail(
            f"Could not reach the LLM provider{where} for model '{model}'. "
            f"Check your network connection and any api_base setting.", exc)
    return f"LLM error for model '{model}': {_provider_detail(exc)}"


def error_class(exc: Exception) -> str | None:
    """Persistent (page-deterministic) failure class, else None (transient).

    Walks the ``__cause__`` chain because the extractor re-raises the real cause
    wrapped in a RuntimeError. Only truncation and malformed-JSON are persistent
    -- they recur identically on the same input. Rate-limit, auth, not-found and
    connection errors are environmental, so they return None and keep retrying.
    """
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, TruncatedResponseError):
            return "truncated"
        if isinstance(cur, (json.JSONDecodeError, ValidationError)):
            return "bad_json"
        cur = cur.__cause__
    if _TRUNCATION_MARKER in str(exc):
        return "truncated"
    return None


def is_persistent_failure(exc: Exception) -> bool:
    """True when the failure is page-deterministic (worth parking on disk)."""
    return error_class(exc) is not None


def truncation_finish_reason(exc: Exception) -> str | None:
    """The provider finish_reason carried by a TruncatedResponseError, if any."""
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, TruncatedResponseError):
            return cur.finish_reason
        cur = cur.__cause__
    return None


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
        # retries: preflight should surface a real error promptly. The max_tokens=1
        # cap always yields finish_reason "length", so opt out of truncation
        # detection -- hitting our own 1-token cap is expected, not a model fault.
        _complete(kwargs, max_retries=0, rate_limit_retries=0,
                  detect_truncation=False)
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


def _finish_reason(choice: object) -> str | None:
    """The provider's finish_reason for a completion choice (dict or object)."""
    if isinstance(choice, dict):
        return choice.get("finish_reason")
    return getattr(choice, "finish_reason", None)


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
              rate_limit_retries: int = _RATE_LIMIT_RETRIES,
              detect_truncation: bool = True) -> tuple[str, Usage | None]:
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
            choice = response["choices"][0]
            content = choice["message"]["content"]
            usage = usage_from_response(response)
            # A length-capped response is incomplete JSON. Surface it as a typed
            # error so the caller can break the loop (retry hotter) rather than
            # feed truncated text to the parser. ``detect_truncation`` (not the
            # mere presence of max_tokens) gates this: the extraction guardrail
            # sets max_tokens AND wants detection, while the check_model preflight
            # sets max_tokens=1 and opts out, since hitting it is expected there.
            if detect_truncation \
                    and _finish_reason(choice) in _TRUNCATION_FINISH_REASONS:
                raise TruncatedResponseError(
                    f"{_TRUNCATION_MARKER} (finish_reason={_finish_reason(choice)})",
                    usage=usage, finish_reason=_finish_reason(choice))
            return content, usage
        except TruncatedResponseError:
            raise  # deterministic; retrying as a transport blip would just re-burn
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
                *, max_output_tokens: int | None = None,
                ) -> tuple[list[Person], Usage | None]:
    """Call the LLM and return (validated people, token usage) for one chunk.

    Retries once on a bad response, always billing the failed attempt too:
    - truncation (output cut off at the token cap): re-issue the original request
      at a higher temperature to break the greedy-decoding repetition loop. The
      truncated text is NOT echoed back -- it can be enormous and would re-prime
      the loop. If the retry still truncates (a genuinely huge page, not a loop),
      the error propagates so the page is left for a later/smaller-chunk run.
    - malformed-but-complete JSON: reprompt with a correction, also hotter.
    Transport errors get backoff inside ``_complete``.
    """
    messages = build_messages(chunk_text)
    kwargs: dict = {"model": model, "messages": messages, "temperature": 0}
    if api_base:
        kwargs["api_base"] = api_base
    if max_output_tokens:
        # Output guardrail: a runaway repetition loop hits this instead of the
        # model's full ceiling, so it fails cheap and as a detectable truncation.
        kwargs["max_tokens"] = max_output_tokens

    try:
        content, usage = _complete(kwargs)
        return _parse(content), usage
    except TruncatedResponseError as exc:
        content, retry_usage = _complete({**kwargs, "temperature": _RETRY_TEMPERATURE})
        return _parse(content), sum_usage([exc.usage, retry_usage])
    except (json.JSONDecodeError, ValidationError):
        repair = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content":
                "That was not valid JSON in the required schema. Respond again "
                "with ONLY the JSON object, no prose."},
        ]
        content, repair_usage = _complete(
            {**kwargs, "messages": repair, "temperature": _RETRY_TEMPERATURE})
        return _parse(content), sum_usage([usage, repair_usage])
