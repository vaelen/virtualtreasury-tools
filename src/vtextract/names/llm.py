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
