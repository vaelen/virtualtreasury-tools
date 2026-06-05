# Name-extraction scorecard (30 models)

Quality ranking of the **30** benchmarked models on the `vtextract names`
person-NER task, scored against a **cross-model consensus ground truth**.

This revision reflects a fresh run on a **Linux box** (the previous scorecard
was a Mac run) and a different model set: it **adds** DeepSeek (`deepseek-chat`,
`deepseek-reasoner`), the full Gemini 2.5 lineup (`flash`, `flash-lite`, `pro`),
`claude-opus-4-8`, and four more small local models (`llama3.2:1b`,
`llama3.2:3b`, `qwen2.5:3b`, `qwen2.5:14b`, `qwen3:14b`), and **drops** two of
the slow partial-coverage models from last time (`gpt-oss:20b`,
`qwen3:30b-a3b`). The third, the MoE `qwen3.6:35b-a3b`, was **re-run and is
included** here — it is the slowest model in the field and still only completed
7/10 files, but it posts the **highest precision** of any model (0.94).

The P/R/F1 columns are now produced **natively by the benchmark tool**
(`vtextract.namebench`) and captured verbatim in `bench.txt` — no manual
recomputation this run. All numbers below come straight from that table plus the
on-disk `times.json`.

## Method

- **Ground truth** = per file, a normalized name is "true" if a strict majority
  of the models that *ran that file* extracted it. Names only one or two models
  found (likely hallucinations or OCR-variant duplicates) are excluded.
- **Precision** = fraction of a model's extracted names that reached consensus;
  **Recall** = fraction of consensus names the model found; **F1** their mean.
- Names are normalized (lowercase, honorifics/titles stripped, punctuation
  removed) before comparison.

> **Coverage is near-complete this run.** 26 of 30 models finished all 10 files;
> four are partial: the three smallest models (`llama3.2:1b` 8/10, `llama3.2:3b`
> and `qwen2.5:3b` 9/10), which are broken on quality anyway, plus
> `qwen3.6:35b-a3b` (7/10), which is partial not from weakness but from sheer
> latency — it timed out / DNF'd on the longest documents. Read its high F1
> (0.70) with that coverage caveat: it only emitted names on 3 of the 7 files it
> reached. For the other 26 models the "DNF inflates F1" caveat no longer bites,
> so the separate easy-subset table has been dropped.
>
> The corpus has 10 files but only ~7 carry real person lists: three short docs
> (`NAI_..._07_0036`, `VRTI_CEN_Report_1871`, `op1246585`) are essentially
> empty, so a healthy `Empty` count is **3**. `Empty` above 3 means the model is
> missing people on documents that actually have them. The two hard documents
> are the `tcd` ~70-name rent-roll and `NAI_..._06` — where weak models collapse.

## Full corpus (10 files), sorted by F1

| Model | P | R | F1 | Files | Empty | Persons | Median s | s/name | Notes |
|-------|--:|--:|---:|------:|------:|--------:|---------:|-------:|-------|
| anthropic/claude-sonnet-4-6 | 0.80 | 0.99 | **0.88** | 10 | 3 | 108 | 2.94 | 0.50 | Best overall; near-perfect recall |
| deepseek/deepseek-reasoner | 0.75 | 0.99 | 0.86 | 10 | 3 | 114 | 22.79 | 2.70 | Excellent quality, but slow (reasoning) |
| anthropic/claude-opus-4-8 | 0.75 | 0.99 | 0.85 | 10 | 3 | 115 | 3.11 | 0.52 | Top-tier, but no edge over sonnet at higher cost |
| deepseek/deepseek-chat | 0.76 | 0.93 | 0.84 | 10 | 3 | 106 | 2.06 | 0.34 | **Standout value** — fast, cheap, accurate |
| gemini/gemini-2.5-flash-lite | 0.74 | 0.99 | 0.84 | 10 | 3 | 117 | **1.21** | **0.17** | Fastest cloud at this quality; best value |
| gemini/gemini-2.5-flash | 0.73 | 0.98 | 0.83 | 10 | 3 | 117 | 9.83 | 1.22 | Good, but flash-lite beats it on speed |
| gemini/gemini-2.5-pro | 0.72 | 0.98 | 0.83 | 10 | 3 | 118 | 16.72 | 1.75 | No quality gain over flash-lite, ~14× slower |
| mistral/mistral-large-latest | 0.73 | 0.95 | 0.83 | 10 | 3 | 113 | 6.26 | 1.64 | Strong; slow, high-variance latency |
| anthropic/claude-haiku-4-5 | 0.72 | 0.94 | 0.82 | 10 | 3 | 114 | 2.05 | 0.30 | Current `names` default; fast and solid |
| openai/gpt-4.1 | 0.71 | 0.92 | 0.80 | 10 | 3 | 113 | 1.99 | 0.35 | Reliable quality/speed balance |
| ollama/qwen3:14b | 0.74 | 0.86 | 0.80 | 10 | 4 | 101 | 81.89 | 14.77 | **Best local** — finished all 10; brutally slow |
| mistral/mistral-small-latest | 0.70 | 0.90 | 0.79 | 10 | 4 | 111 | **1.10** | 0.22 | Fastest median overall |
| openai/gpt-4.1-mini | 0.68 | 0.87 | 0.77 | 10 | 3 | 111 | 2.79 | 0.45 | Solid cheap cloud |
| mistral/ministral-8b-latest | 0.67 | 0.90 | 0.76 | 10 | 3 | 117 | 5.07 | 0.58 | Decent; uncalibrated |
| openai/gpt-4o-mini | 0.74 | 0.68 | 0.71 | 10 | 4 | 80 | 1.48 | 0.59 | Precise but misses ~⅓ |
| ollama/qwen3.6:35b-a3b | **0.94** | 0.56 | 0.70 | **7** | 4 | 16 | 266.86 | 180.16 | Highest precision in field, but only ran 7/10; unusably slow MoE |
| ollama/llama3.1:8b | 0.61 | 0.79 | 0.69 | 10 | **0** | 114 | 4.68 | 1.02 | Hallucinates; never returns empty |
| ollama/gemma2:9b | 0.67 | 0.69 | 0.68 | 10 | 5 | 90 | 1.49 | 0.73 | Mediocre but stable |
| ollama/granite3.3:8b | 0.71 | 0.53 | 0.61 | 10 | **8** | 65 | 1.34 | 0.66 | Broken: empty on 8/10, dumps names only on rent-roll |
| openai/gpt-4.1-nano | 0.69 | 0.55 | 0.61 | 10 | **9** | 70 | 0.60 | 0.34 | Too weak: empty on 9/10 |
| ollama/gemma3:12b | 0.52 | 0.67 | 0.59 | 10 | 4 | **111** | 7.64 | 1.14 | Full coverage but low precision |
| ollama/mistral:7b | 0.66 | 0.52 | 0.58 | 10 | 4 | 68 | 1.75 | 0.83 | Low recall |
| ollama/llama3.2:3b | 0.59 | 0.46 | 0.52 | **9** | 1 | 66 | 1.09 | 0.48 | Weak; dropped a file |
| ollama/qwen2.5:14b | 0.51 | 0.51 | 0.51 | 10 | 5 | 87 | 2.81 | 1.37 | Surprisingly weak for its size |
| ollama/phi4 | 0.48 | 0.47 | 0.47 | 10 | 4 | 86 | 5.50 | 1.56 | Weak + slow |
| ollama/qwen3:8b | 0.56 | 0.28 | 0.37 | 10 | 4 | 43 | 46.98 | 25.39 | Low recall *and* extremely slow |
| ollama/qwen2.5:7b | 0.78 | 0.16 | 0.27 | 10 | 7 | 18 | 0.99 | 0.93 | Broken: bails on long input |
| ollama/qwen2.5:3b | 0.75 | 0.16 | 0.26 | **9** | 5 | 16 | 0.71 | 25.15 | Broken; one file timed out (~394 s) |
| ollama/mistral-nemo:12b | 0.40 | 0.07 | 0.12 | 10 | 7 | 15 | 1.41 | 1.74 | Broken: 7/10 empty, 15 names total |
| ollama/llama3.2:1b | 0.29 | 0.03 | 0.05 | **8** | 1 | 7 | 0.66 | 34.94 | Effectively nonfunctional on this task |

## Takeaways

- **`claude-sonnet-4-6` is still the quality leader (F1 0.88)**, with
  `deepseek-reasoner` (0.86) and `claude-opus-4-8` (0.85) right behind — all
  three hit ~0.99 recall. Opus shows **no advantage over sonnet** here at higher
  cost, and the reasoner's quality comes at a 10× latency penalty (median 23 s,
  s/name 2.70).
- **The new value champions are `gemini-2.5-flash-lite` and `deepseek-chat`
  (both F1 0.84).** flash-lite is the fastest cloud model in the whole field
  (median **1.21 s**, **0.17 s/name**) yet matches the mid-frontier on quality —
  it's a strong candidate to become the `names` default over `haiku-4-5` (0.82).
  `deepseek-chat` is nearly as fast (2.06 s) and similarly cheap.
- **Bigger Gemini is not better Gemini.** `gemini-2.5-pro` (0.83) does **not**
  beat `flash-lite` (0.84) on quality while being ~14× slower (16.7 s vs 1.2 s).
  `flash` sits between them on speed with no quality edge. Use flash-lite.
- **`qwen3:14b` is the best local model and the first to be genuinely
  cloud-adjacent** — F1 0.80, tying `gpt-4.1`, and it finished all 10 files
  including the hard ones. But it's **unusable at scale**: median 82 s/file
  (max 689 s ≈ 11 min), s/name 14.77 vs cloud's 0.17–0.6. Quality-per-token is
  there; throughput is not.
- **`qwen3.6:35b-a3b` posts the highest precision in the whole field (0.94)
  but is the slowest model benchmarked, by a wide margin.** Median **267 s/file**
  (max 828 s ≈ 14 min), s/name **180** — ~1000× flash-lite's. That latency is
  why it only finished 7/10 files, and on 4 of those 7 it returned empty, so its
  recall (0.56) and 0.70 F1 are coverage-limited rather than a true quality
  ceiling. When it does emit a name it is almost always right, but at this
  throughput it is a research curiosity, not a usable extractor.
- **Most other locals are weak or broken.** `llama3.1:8b` (0.69) hallucinates
  and never returns empty; `gemma3:12b` (0.59) gets full coverage but poor
  precision. The genuinely broken set — empty on most real documents or bailing
  on long input — is `granite3.3:8b`, `gpt-4.1-nano` (the one broken *cloud*
  model), `qwen2.5:7b`, `qwen2.5:3b`, `mistral-nemo:12b`, and `llama3.2:1b`
  (effectively nonfunctional at 0.05). `qwen3:8b` is the worst combination:
  low recall (0.28) *and* 25 s/name.
- **`s/name` remains the meaningful throughput metric** — latency is
  output-bound (number of names emitted), not input-bound. It's inflated for the
  broken tiny models (`llama3.2:1b` 34.9, `qwen2.5:3b` 25.2) because they emit
  almost no names while occasionally timing out, so read those rows as "broken,"
  not "slow."
