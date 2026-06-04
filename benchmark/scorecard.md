# Name-extraction corrected scorecard

Quality ranking of the 13 benchmarked models on the `vtextract names`
person-NER task, scored against a **cross-model consensus ground truth**
instead of the raw confidence counts in `bench.txt` (which double-count
persons + aliases and are not comparable across models).

## Method

- **Ground truth** = per file, a normalized name is "true" if a strict majority
  of the models that ran on that file extracted it (≥7 of 13). This yields 88
  consensus names across the 10 documents. Names only one or two models found
  (likely hallucinations or OCR-variant duplicates) are excluded.
- **Precision** = fraction of a model's extracted names that reached consensus.
- **Recall** = fraction of consensus names the model found.
- Names are normalized (lowercase, honorifics/titles stripped, punctuation
  removed) before comparison.

**Caveat:** strict-majority on exact normalized form slightly *understates*
recall for everyone on OCR-variant-heavy documents — e.g. the lone real name in
`RCB` ("George Arp" / "Arpum" / "Arpum Dub") split 6/3/… across spellings and
fell just under the 7-vote bar, so it scores as 0 consensus names. The effect is
uniform across models, so the *relative* ranking holds; treat absolute P/R as
approximate.

## Scorecard (sorted by F1)

| Rank | Model | Precision | Recall | F1 | Names found | Median s | Verdict |
|-----:|-------|----------:|-------:|----:|------------:|---------:|---------|
| 1 | anthropic/claude-sonnet-4-6 | 0.81 | 0.99 | **0.89** | 108 | 2.94 | Best overall; near-perfect recall |
| 2 | mistral/mistral-large-latest | 0.75 | 0.97 | 0.85 | 113 | 6.26 | Strong, but slowest cloud + cold spikes |
| 3 | openai/gpt-4.1 | 0.73 | 0.94 | 0.83 | 113 | 1.99 | Excellent quality/speed balance |
| 4 | anthropic/claude-haiku-4-5 | 0.72 | 0.93 | 0.81 | 114 | 2.05 | Best value; the names-default tier |
| 5 | mistral/mistral-small-latest | 0.71 | 0.90 | 0.79 | 111 | **1.10** | Fastest; slightly recall-light |
| 6 | mistral/ministral-8b-latest | 0.68 | 0.90 | 0.77 | 117 | 5.07 | Decent; uncalibrated (stamps all "high") |
| 7 | openai/gpt-4.1-mini | 0.68 | 0.85 | 0.75 | 111 | 2.79 | Solid cheap workhorse |
| 8 | openai/gpt-4o-mini | 0.75 | 0.68 | 0.71 | 80 | 1.48 | Precise but misses ~⅓ of names |
| 9 | ollama/llama3.1:8b | 0.54 | 0.77 | 0.63 | 112 | 14.86 | **Hallucinates** (invented "George Orwell" from OCR noise; placenames as people); only ran 9/10 files |
| 10 | ollama/mistral:7b | 0.65 | 0.51 | 0.57 | 69 | 10.95 | Low recall, slow |
| 11 | ollama/gemma2:9b | 0.51 | 0.51 | 0.51 | 89 | 10.78 | Safe (no hallucination) but mediocre |
| 12 | ollama/phi4 | 0.48 | 0.47 | 0.47 | 85 | 28.02 | Worst usable + very slow |
| 13 | ollama/qwen2.5:7b | 0.78 | 0.16 | **0.26** | 18 | 6.24 | **Broken**: bails on long input (5 names on a 70-name roll); high P is an artifact of barely extracting |

## Takeaways

- **Cloud models dominate.** Top 8 are all cloud; the best local model
  (llama3.1) ranks 9th and hallucinates.
- **Pick by use case:** `claude-haiku-4-5` is the value sweet spot (rank 4,
  2 s median); `gpt-4.1` if you want the quality/speed Pareto point;
  `claude-sonnet-4-6` for maximum recall.
- **Avoid locally:** `qwen2.5:7b` (won't extract) and `llama3.1:8b`
  (hallucinates). `gemma2:9b` is the least-bad local option.
- **Latency is output-bound, not input-bound.** Every model's slowest call is
  the 1.5 KB rent-roll (≈70 names to emit), not the 6.6 KB file — so `ms/byte`
  misleads and `s/name` is the better throughput metric. Local models also pay a
  one-time cold-start tax (first call 124–317 s).
