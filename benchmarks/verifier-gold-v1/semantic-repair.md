# Contextual sense repair and occurrence equivalence (experimental v1)

This harness addresses a different question from the old verifier: can a small
model **recover the right dictionary meaning**, and can it recognize whether two
occurrences teach the same meaning? It does not modify production generation,
the frozen hybrid 9B baseline, or any learned-word identities.

## Decisions and boundaries

- **Sense selection:** offer spelling/reading-compatible JMdict senses without
  narrowing them using the original POS guess or construction-specific rules.
  English, the previous selected sense, and review labels are not in this prompt.
  A model cannot supply its own definition. Missing/oversized option sets abstain.
- **Correction:** retain a stable selected sense even when it differs from the
  initial guess. Independently check whether the subtitle expresses the selected
  meaning. Stable support permits a proposed `repair` or `retain`; unsupported
  translation produces `reject`; disagreement or uncertainty produces `abstain`.
- **Equivalence:** compare the target's contribution in two Japanese occurrences,
  with dictionary possibilities rather than asserted correct glosses. Return
  `same`, `different`, or abstain. The inputs must share a lemma and reading.
  English is excluded so matching translations cannot decide the answer.
- **Consistency:** each decision is asked twice with rotated answer labels,
  including the uncertainty option. Equivalence also reverses occurrence order.
  Raw prompts, mappings and outputs are retained. Agreement is a consistency
  check, **not a calibrated probability of correctness**.

Pairwise equivalence is not permission to globally merge two JMdict senses, nor
to take a transitive closure over all pairs. Production clustering needs separate
evidence and safeguards. Reading correction still belongs to the audio gate.
Target-span/construction mistakes may leave no suitable dictionary option; the
benchmark does not silently repair those. Source spans are kept as-is, including
old baseline spans that contain grammatical endings. They need review too.

## Reproducible review queue

From the repository root:

```console
.venv/bin/python -m vocabdeck.semantic_benchmark build \
  --baseline baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/expected-cards.json \
  --old-dataset benchmarks/verifier-gold-v1/dataset.json \
  --output .vocabdeck/benchmarks/semantic-repair-v1-queue.json
```

The existing sources produce **185 distinct cases**: 100 development sense
cases, 40 held-out HxH sense cases, 39 second-show sense cases, and six repeated
lemma/reading pairs from the frozen 200. One duplicate second-show input is
collapsed while preserving both source IDs. Identical inputs across splits
cause an error. The six pairs cover 何, あれ, 分かる, こっち, どっち, and くれる;
they are selected by grouping data, not by a hardcoded vocabulary list.

These are **unreviewed inputs, not 185 gold labels**. The old implicit passes and
earlier assistant assessments do not establish the new semantic answers. The
current pair queue is development-only: held-out word pairs, cross-show pairs,
and independently reviewed labels remain work for VOCAB-2.5.6. The full 200-card
baseline remains frozen even though only its first 100 feed development sense
checks. No one needs to review every new show's deck as part of production;
independent annotation is a benchmark-development requirement.

Each input has a content-derived ID and fingerprint. Changing the sentence,
target, dictionary options, or their definitions invalidates the identity.
Adding labels does not. Gold requires `review_status: "reviewed"` and provenance:

```json
{
  "kind": "explicit_human_semantic_review",
  "reviewer": "actual-reviewer-name",
  "note": "Why this contextual decision is supported; cite review evidence."
}
```

For a sense case, `gold` has `acceptable_sense_keys` (a list of supported keys
from the frozen options; empty for no supported choice) and `subtitle_support`
(`expressed`, `not_expressed`, or `uncertain`). For a pair, it has `relation`
(`same`, `different`, or `uncertain`). Labels must be entered by/with the actual
reviewer, not by renaming an LLM output's provenance. Multiple acceptable sense
keys allow genuinely interchangeable dictionary choices without forcing a
single arbitrary index. Label revision should be version-controlled separately
from model output, and evaluators must not tune on held-out cases.

## Safe diagnostic runs

The runner uses the existing exclusive inference lock, 4 GiB default MLX cap,
6 GiB hard maximum, 3.5 GiB artifact ceiling and at most 512 MiB cache. These are
MLX/model limits, not a guarantee about whole-system memory. Run one process at
a time, check available memory beforehand, and never run the historical 9B
baseline through this path. No model download is needed for cached revisions:

```console
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m vocabdeck.semantic_benchmark run \
  --dataset .vocabdeck/benchmarks/semantic-repair-v1-queue.json \
  --model mlx-community/Qwen3.5-2B-OptiQ-4bit \
  --revision adc8669eb431e3168aeb4e320bd7b757914350e2 \
  --limit 8 --memory-limit-gb 4 \
  --output .vocabdeck/benchmarks/semantic-repair-v1-2b-diagnostic.json
```

After that process exits, repeat with `mlx-community/Qwen3.5-4B-MLX-4bit`, revision
`32f3e8ecf65426fc3306969496342d504bfa13f3`, and a separate output path. Both use
temperature 0, a four-token answer budget, 1024-token KV limit, and one prompt
at a time. The default eight-case limit covers the six occurrence pairs plus two
sense cases; it is a wiring/behavior diagnostic, not an adoption test. Checkpoints
are saved per case; this initial harness has no implicit resume or prediction reuse.

```console
.venv/bin/python -m vocabdeck.semantic_benchmark evaluate \
  --dataset .vocabdeck/benchmarks/semantic-repair-v1-queue.json \
  --predictions .vocabdeck/benchmarks/semantic-repair-v1-2b-diagnostic.json \
  --output .vocabdeck/benchmarks/semantic-repair-v1-2b-scores.json
```

The evaluator rejects stale/duplicate predictions and scores only explicit
semantic gold. Per-split output exposes false repairs, false accepts, false
merges, retained distinctions, wrong distinctions, invalid answers, order
disagreements, abstentions, valid-card coverage and equivalence recall. Runtime
and unreviewed/unpredicted cases remain visible. Missing denominators yield null,
not perfect precision. With this initial queue, **zero cases are scored**.
`production_ready` remains false: neither passing a tiny smoke test nor rejecting
everything can demonstrate a useful, reliable self-service deck.

Next: VOCAB-2.5.6 adds independent semantic labels and a broader matched model
comparison. VOCAB-2.7 production deduplication now depends on that evidence.

## Initial eight-case diagnostic (2026-09-05)

Both cached models completed sequentially and released the inference guard.
Times measure the eight-case loop, excluding model loading. Peak is MLX-reported
decimal GB, not whole-process RSS or GiB; the configured cap is 4 GiB.

| Model | Time | Prompt calls | Peak MLX GB |
| --- | ---: | ---: | ---: |
| Qwen3.5 2B OptiQ | 30.78 s | 18 | 2.479 |
| Qwen3.5 4B MLX | 80.02 s | 20 | 3.486 |

The call counts differ because a stable sense selection triggers subtitle
checks. These tiny runs do not establish general throughput or model quality.

| Occurrence pair | 2B decision | 4B decision |
| --- | --- | --- |
| 何 | abstain (order disagreement) | same |
| あれ | abstain (order disagreement) | same |
| 分かる | different | abstain (order disagreement) |
| こっち | abstain (order disagreement) | same |
| どっち | abstain (order disagreement) | abstain (order disagreement) |
| くれる | different | abstain (order disagreement) |

Neither model accepted either of the two sense cases (いい, これ). The 4B
`same` decision for あれ deserves particular scrutiny: the source sentences are
`≪何だ あれは…≫` and `あれ？`, previously discussed as referential versus reaction
usage. That is a warning against trusting stable output as semantic correctness,
not an independently scored label. No model is adopted and no pair is merged.

Full prompts/responses and unscored reports are saved under `.vocabdeck/benchmarks/`
as `semantic-repair-v1-{2b,4b}-diagnostic.json` and
`semantic-repair-v1-{2b,4b}-scores.json`. The queue and outputs are local generated
artifacts; reproduce them with the commands above. The evaluator reports eight
unscored development predictions per model and zero scored cases in every split.
