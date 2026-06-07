# Name Extraction: Cost Retrospective

_How we benchmarked models, projected the cost of running person-NER over the
whole archive, hit a wall on dense pages, built safeguards — and still spent
more than expected. Written 2026-06-07._

## TL;DR

We benchmarked 30 LLMs for person extraction, picked `gemini-2.5-flash-lite`
on a quality/cost/speed basis, and projected a cheap full-archive run. The
projection was built from a 10-file sample of small pages. The real archive is
full of **dense name-index pages** that the sample never represented; those
pages drove **repetition loops**, **output-token blow-ups**, and
**recitation/safety blocks** that the benchmark could not have predicted. By the
time ~83% of the archive was processed we had spent roughly **$90–100 (~15,000
JPY)** — several times the naive projection. This document records what went
wrong, the safeguards we added along the way, the post-hoc root-cause analysis,
and the schema change that addresses the dominant remaining cost.

## 1. Goal

`vtextract names` runs an LLM over each page transcription in the archive and
writes a durable `{page_key}.names.json` sidecar listing the people on that
page. The archive holds **174,494** page transcriptions. Running a cloud LLM
over every one of them is the expensive part, so before committing we wanted to
(a) pick the best model for the job and (b) estimate the total cost.

## 2. Phase 1 — Benchmarking the models (`vtnamebench`)

We built `vtnamebench`, which runs the exact production extraction pipeline
(`chunk_text` → `find_people` → `merge_people`) over a fixed corpus and scores
each model. It covered **30 models** across Ollama (local), OpenAI, Anthropic,
DeepSeek, Mistral and the full Gemini 2.5 lineup, reporting precision/recall/F1
against a hand-labelled gold set plus latency distribution and names-per-token.

Results (see `benchmark/scorecard.md`):

- `claude-sonnet-4-6` was the quality ceiling (F1 0.88) but expensive.
- **`gemini-2.5-flash-lite` (F1 0.84) was the value champion** — tied with
  `deepseek-chat` on quality, the fastest cloud model in the field (~1.2 s
  median), at the cheapest published price tier ($0.10/M input, $0.40/M
  output). We selected it.
- Local Ollama models were either too slow (minutes per page) or broke on long
  input. The cloud models at flash-lite's price were 10–30× cheaper than Sonnet
  for comparable quality.

**The flaw, in hindsight:** the benchmark corpus was **10 files averaging 2,448
bytes, max 6,582 bytes**. It was chosen to be quality-diverse, not
size-representative. Nothing in it was large enough to trigger the failure modes
that dominate the real bill.

## 3. Phase 2 — The cost projection

We extrapolated from the benchmark's per-page token usage to the full archive.
Because the sample pages were small, the implied per-page output was small, and
the full-archive projection came out in the low tens of dollars. That number is
what set expectations.

The projection's hidden assumptions:

1. Per-page output tokens scale like the benchmark sample (small).
2. Every page completes in roughly one model call.
3. No pathological pages.

All three are false for the real archive, as the next sections show.

## 4. Phase 3 — Dense pages break things

The archive is dominated by **registry and index pages**: long, repetitive lists
of names ("John (Rev.) and Jane Broom, ML. 1765 …" line after line). Production
page sizes tell the story:

| | Files | Avg bytes | Max bytes |
|---|--:|--:|--:|
| Benchmark sample | 10 | 2,448 | 6,582 |
| Real archive | 174,494 | 3,980 | 45,065 |

The real archive averages 1.6× the sample size, and its largest page is **7×**
the benchmark's largest. On these dense pages two things went wrong:

- **Repetition loops.** Greedy decoding (temperature 0) on highly repetitive
  text falls into a loop, emitting names — real or hallucinated — until it hits
  the model's output ceiling. For flash-lite that ceiling is **65,536 tokens**.
  A page that should cost a few hundred output tokens instead cost tens of
  thousands.
- **Truncation.** A response cut off at the token ceiling is incomplete JSON.
  Naively parsing it throws a misleading delimiter error, and the wasted tokens
  are billed anyway.

## 5. Safeguards we built

In response we added several layers of protection in `names/llm.py`:

### 5.1 Output-token guardrail
A per-call `max_output_tokens` cap (config `[names].max_output_tokens`, default
**12,000**). A runaway loop now hits our cap instead of the model's 65,536
ceiling — failing cheap. 12,000 sits well above the p99 of legitimate
extractions (~7,500 output tokens), so real pages are unaffected. This was the
single biggest per-incident cost reduction (~9× on the worst pages).

### 5.2 Truncation detection
When a completion's `finish_reason` is in `("length", "max_tokens")` we raise a
typed `TruncatedResponseError` carrying the wasted usage, instead of feeding
broken JSON to the parser. The detection is gated by an explicit
`detect_truncation` flag so the `check_model` preflight (which deliberately caps
at 1 token) isn't misreported as a failure.

### 5.3 Retry-temperature tuning
A truncated response is re-issued **once at a higher temperature** to break the
greedy-decoding loop. We measured the threshold on the real failing pages:

- temperature **0.3** — still looped to the cap (insufficient).
- temperature **0.5** — broke the loop on every sampled page **and** kept the
  JSON valid.
- temperature **0.7** — sometimes produced malformed JSON.

So `_RETRY_TEMPERATURE = 0.5` — the lowest reliable loop-breaker. Pass-1
determinism (temp 0) is preserved; only the retry runs hot. The truncated text
is **not** echoed back into the retry (it can be enormous and would re-prime the
loop).

### 5.4 Malformed-JSON repair
A complete-but-invalid JSON response triggers one corrective reprompt (also at
0.5). Both the failed and repair attempts are billed, so usage sums both.

### 5.5 Recitation / empty-response handling
Gemini flags dense, list-like text for **recitation/safety** and returns a
completion with `content = None` and a non-truncation `finish_reason`. This
originally crashed with a cryptic `'NoneType' object has no attribute 'strip'`
and was misclassified as a transient failure, so the page re-failed every run.
We added a typed `EmptyResponseError`: it's classified as a *persistent* failure
and **parked** as an error sidecar (visible in `names --list-failed`, retryable
with `--retry-failed --model <other>`), with an actionable message naming the
recitation cause. These pages no longer burn retry budget.

### 5.6 Rate-limit backoff
429s get their own generous retry budget (`_RATE_LIMIT_RETRIES = 6`, honoring
`Retry-After`, else exponential 5 s → 60 s), independent of the short transport
backoff, so a slow rate-limit recovery never burns the transport retries.

## 6. Phase 4 — The bill still came in high

After processing **144,920** pages (83% of the archive) the spend was clearly
several times the projection. We reconstructed the actual cost from the recorded
per-page `usage` blocks in the sidecars (ground truth for successful pages):

| | Tokens | Cost @ flash-lite |
|---|--:|--:|
| Input | 286,497,728 | $28.65 |
| Output | 129,445,828 | **$51.78** |
| Recorded subtotal (144,920 pages) | | **~$80.4** |
| + 1,551 parked error pages (untracked tokens) | est. | +$10–20 |
| **Total** | | **≈ $90–100 ≈ 15,000 JPY** |

(Token counts are exact; the per-token price is flash-lite's published rate and
should be confirmed against the Google billing console, but it reproduces the
observed JPY spend.)

Per-page averages: **1,977 input / 893 output tokens** — far above what a sample
of ≤6.6 KB pages implied.

## 7. Why it overran — the root causes, ranked

1. **The benchmark sample was not size-representative.** Projecting from 10
   small pages could not capture the dense-page tail (§4). This is the upstream
   cause of everything below.

2. **Output dominates and was under-projected.** Output is 4× the input price
   and is **64% of the bill** ($51.78). Name extraction emits a JSON entry per
   person; dense pages emit huge lists.

3. **Repetition-loop waste is savagely concentrated.** **2,636 pages (1.82% of
   pages) produced 30.1% of all output tokens.** The output-token histogram is
   bimodal: a normal cluster under 2,000, then a spike at the 12,000 guardrail
   and a tail reaching **68,886** (pre-guardrail pages that hit the 65,536
   ceiling, billed for the failed attempt *and* the retry).

4. **No prompt caching.** Every sidecar shows `cached: 0`. The ~530-token system
   prompt is re-sent as fresh, full-price input on every one of 145k+ calls.

5. **Errored pages burn invisible tokens.** The 1,551 parked failures (mostly
   truncation loops at the cap, billed twice) generated tokens recorded in *no*
   sidecar — invisible to sidecar-based tracking, fully real on the bill.

## 8. The prompt-caching dead end

Caching looked like an obvious lever (it would attack driver #4), but it does
not work for this workload. Gemini's minimum cacheable prefix is **1,024 tokens**
(flash) / 2,048 (pro); our only static prefix is the **530-token** system prompt
— below the floor — so `cache_control` is a silent no-op, and flash-lite is
separately reported to return `cached_content_token_count = 0` even when
thresholds are nominally met. The `cached: 0` we already saw was expected, not a
misconfiguration. Padding the prompt to clear the threshold would *add* cost.
Caching only ever touches input, anyway, while the bill is output-dominated.

## 9. What we did about it — the compact schema

Since the cost is output-bound, we attacked the output. The sidecar schema went
from a verbose per-person object to a **compact array**, and confidence was
dropped entirely:

```jsonc
// v1 (old) — per person
{"canonical": "B. McHugh", "confidence": "high",
 "aliases": [{"text": "B. Mchugh", "confidence": "high"}]}

// v2 (new) — per person
["B. McHugh", "B. Mchugh"]   // [canonical, *verbatim surface forms]
```

Confidence was near-uniform "high" noise from flash-lite and added a
`,"confidence":"high"` to every name and every alias. Removing it plus the JSON
scaffolding roughly **3×'s less output on name-bearing pages, and much more on
dense index pages** where the per-name overhead dominates — i.e. exactly the
pages driving the bill. The change spans the extraction models/prompt/merge, the
index ingester (the `confidence` columns and the `vtindex people --confidence`
filter were removed; `SCHEMA_VERSION` bumped to force a rebuild), and
`vtnamebench`. A one-time `scripts/migrate_sidecars.py` converts existing v1
sidecars in place (atomic, idempotent, lossy only in dropping confidence).

The remaining lever, not yet taken, is **pre-screening oversized/dense pages**
(route them to a smaller `chunk_size` or park them) so a single looping page
can't cost 50–100× a normal one.

## 10. Lessons

- **Benchmark on a size- and shape-representative sample, not just a
  quality-diverse one.** The cost-driving failure modes (loops, truncation,
  recitation) live in the tail of the size distribution, and a small-page sample
  hides them entirely.
- **For extraction-style tasks, project on output tokens.** Output is the
  expensive side and the one that explodes on pathological input.
- **Track wasted tokens, including failures.** Error sidecars recorded no usage,
  so a real and recurring cost was invisible. (Follow-up: record usage on error
  sidecars too.)
- **Verify "obvious" optimizations against the provider's actual constraints.**
  Prompt caching was a confident recommendation that turned out to be a no-op
  below Gemini's token threshold.
- **Cap the blast radius early.** The `max_output_tokens` guardrail should have
  been in place from the first run; it was the cheapest, highest-leverage
  control and we added it reactively.

## Appendix — key numbers

- Archive: 174,494 page transcriptions; 144,920 processed (83%), 1,551 parked
  errors, ~28,023 remaining at time of writing.
- Recorded usage (success pages): 286.5M input + 129.4M output tokens;
  `cached: 0`; avg 1,977 in / 893 out per page; max 68,886 output on one page.
- Loop tail: 2,636 pages (1.82%) = 30.1% of all output tokens.
- Benchmark corpus: 10 files, avg 2,448 / max 6,582 bytes. Production: avg 3,980
  / max 45,065 bytes.
- Model: `gemini-2.5-flash-lite`, F1 0.84; published price $0.10/M in,
  $0.40/M out.
- Guardrail: `max_output_tokens = 12,000`; retry temperature 0.5; truncation
  finish reasons `("length", "max_tokens")`; rate-limit retries 6 (5–60 s
  backoff).
- Estimated total spend at 83% processed: ~$90–100 (~15,000 JPY).
