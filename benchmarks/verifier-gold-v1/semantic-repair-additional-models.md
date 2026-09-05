# Additional eight-case model diagnostics (2026-09-05)

VOCAB-2.5.6 is **in progress**, not validated for production. At the user's
request, the three candidates from the earlier verifier experiments were run
on the exact same first eight cases as the [initial comparison](semantic-repair.md).
There are six occurrence pairs followed by two sense cases (いい and これ).

No prompt, parser, dictionary choices, baseline, or production setting changed.
All three used cached pinned models, offline mode, temperature 0, four generated
tokens, 1024-token KV limit and one prompt at a time. Every model ran in its own
process **after the preceding process exited**, using the exclusive inference
lock and 4 GiB MLX cap. All completed cleanup. System memory reported 67% free
before the first run and 60% free before Phi; these are snapshots, not process
peak measurements.

## Observed results, not gold accuracy

| Model (all 4-bit) | Eight-case time | MLX peak GB | Pair outcomes | Sense outcomes |
| --- | ---: | ---: | --- | --- |
| Gemma 2 2B Japanese | 26.07 s | 2.206 | Six `same` | Two order disagreements |
| Qwen3 1.7B | 28.61 s | 1.719 | Six invalid-format abstentions | Two order disagreements |
| Phi-4 Mini | 37.77 s | 3.187 | Six invalid-format abstentions | Two invalid-format abstentions |

Each made 16 prompt calls. Times exclude model loading. Memory is decimal GB
reported by MLX, not total process RSS or GiB. No run exceeded the configured
4 GiB limit. The initial 2B/4B runs took 30.78/80.02 seconds and peaked at
2.479/3.486 GB, but made 18/20 calls because stable sense decisions triggered
extra subtitle checks; wall-clock totals are not identical-work throughput.

Gemma's six `same` decisions include both `≪何だ あれは…≫` and `あれ？`, the
referential/reaction distinction discussed with the user. Its stable outputs
therefore do not resolve the concern about over-merging.

Qwen and Phi frequently echoed the option text instead of returning only a
letter. Examples preserved in the raw artifacts:

- Qwen3 1.7B, first pair: `B. Different meaning` / `B`.
- Phi-4 Mini, first pair: `C. Uncertain` / `C. Same learner`.
- Phi-4 Mini, これ: `A. this;` / `H. this;`.

The option letters rotate. Identical letters need not represent identical
decisions, and different letters may represent the same decision. The strict
parser rejects extra text; we did **not** retrospectively relax it or turn these
outputs into accepted answers. Thus these runs show failures of the current
end-to-end prompt/decoding/parser setup, not proof that those models lack
Japanese semantic ability. Output formatting needs separate controlled testing
before interpreting all abstentions as semantic uncertainty.

Every output was passed through the evaluator: eight cases per model matched
the frozen input fingerprints, no duplicates/stale inputs were accepted, and
all eight remained **unscored** because there are no explicit independent
semantic labels for this queue. No accepted repair/retain decision occurred.
Held-out episode and second-show cases were not run in this diagnostic. No
model is promoted and no dictionary senses are merged.

## Reproduction and artifacts

Use the build command from `semantic-repair.md`, then run the following command
once per row below, waiting for the process to exit before starting another:

```console
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m vocabdeck.semantic_benchmark run \
  --dataset .vocabdeck/benchmarks/semantic-repair-v1-queue.json \
  --model MODEL --revision REVISION --limit 8 --memory-limit-gb 4 \
  --output .vocabdeck/benchmarks/semantic-repair-v1-NAME-diagnostic.json
```

| NAME | MODEL | REVISION |
| --- | --- | --- |
| gemma2-jpn | mlx-community/gemma-2-2b-jpn-it-4bit | c6437fd222e0833f5400b04c58a0e156b225d4b1 |
| qwen3-17b | mlx-community/Qwen3-1.7B-4bit | 3b1b1768f8f8cf8351c712464f906e86c2b8269e |
| phi4-mini | mlx-community/Phi-4-mini-instruct-4bit | ac1c269cb4222a4e136a3d09edad301056c1f36a |

The resulting local `*-diagnostic.json` artifacts contain raw responses, prompts,
label mappings, fingerprints, runtime configuration, peaks and cleanup status.
Each has an accompanying `*-scores.json` produced with the harness `evaluate`
command. Generated artifacts remain under `.vocabdeck/benchmarks/`; the commands
and exact model revisions are recorded here for reproduction.

Broader VOCAB-2.5.6 acceptance criteria remain unchecked: independent semantic
annotation, held-out/cross-show comparisons and a defensible production decision
are still outstanding. The current baseline remains unchanged.
