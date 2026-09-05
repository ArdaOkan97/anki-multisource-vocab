# Verifier gold dataset v1

This directory freezes the model-independent evaluation foundation for the
small, constrained card verifier. `dataset.json` contains four distinct splits:

- `development`: cards 1–100 from the frozen Hunter x Hunter baseline. The five
  explicit user flags remain rejects; all other cards in the reviewed range are
  recorded as the review's implicit passes.
- `heldout_hxh`: a deterministic 40-card review queue from episodes 11–20.
- `second_show`: a deterministic 40-card review queue from High Score Girl.
- `hard_negatives`: human-rejected cases and transparent subtitle mutations
  covering sense, expression, reading/homograph, fragment, slang, and one-word
  failure modes.

The two queues are deliberately marked `unreviewed`; the benchmark never scores
them until a human assigns gold labels. No Qwen or other LLM response is treated
as ground truth. Source hashes, schema versions, prompt versions, acceptance-rule
version, reviewer provenance, and reason categories are stored in the dataset.

Build the frozen artifact with:

```console
vocabdeck build-verifier-gold-dataset \
  --baseline baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/expected-cards.json \
  --human-review baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/human-review.json \
  --heldout-hxh .vocabdeck/benchmarks/hxh-e11-e20-candidates.json \
  --second-show .vocabdeck/benchmarks/high-score-girl-e01-candidates.json \
  --queue-size 40 --output benchmarks/verifier-gold-v1/dataset.json
```

Run a candidate model through the repository's exclusive 4 GiB-default memory
guard (6 GiB hard ceiling):

```console
vocabdeck run-verifier-benchmark \
  --dataset benchmarks/verifier-gold-v1/dataset.json \
  --model mlx-community/Qwen3.5-2B-OptiQ-4bit \
  --revision adc8669eb431e3168aeb4e320bd7b757914350e2 \
  --output predictions.json
```

Then evaluate the prediction artifact with:

```console
vocabdeck evaluate-verifier-benchmark \
  --dataset benchmarks/verifier-gold-v1/dataset.json \
  --predictions predictions.json \
  --json-output report.json --html-output review.html
```

The report includes false accepts, accepted precision and its 95% Wilson
interval, coverage, abstentions, option-order instability, invalid outputs,
throughput, and peak memory. It refuses to claim the 99.5% production precision
target unless at least 600 gold cases were accepted and the confidence interval's
lower bound clears the target.

## Provisional 4B semantic validation

`semantic-validation-105.json` freezes all 105 currently labeled cases as one
semantic-validation cohort: 99 semantic positives and six semantic negatives.
It includes the reported contextual-sense failures and clean counterexamples,
while audio, duplicate-sentence, and curriculum-accounting defects remain the
responsibility of their dedicated gates.

Qwen3.5 4B MLX 4-bit prompt v1 accepted 59 semantic positives and no semantic
negatives. Semantic accepted precision was therefore 1.0 on this cohort, with
59.6% positive coverage and 46 abstentions. The run peaked at 3.171 GiB under
the 4 GiB guard and cleaned up successfully. This is enough to advance the
configuration to an end-to-end deck regression, but not enough to claim the
repository's 99.5% production precision target: only 59 gold cases were
accepted, far below the required 600.

The ordinary production-label metric reports four false accepts because those
four cases are non-text defects. They are deliberately excluded from the
semantic false-accept count; treating them as text-verifier failures would hide
which independent guardrail still needs work.

## Episodes 1–10 regression decision

The end-to-end experiment searched 7,687 ranked sentence occurrences for 1,500
word-senses. Each word-sense advanced to its next easiest sentence after a
rejection and discarded its remaining alternatives after acceptance. Unknown
word counts remained hard limits; relative unknown difficulty was changed from
an exclusion to a sorting preference after the hard rule caused a curriculum
dead end.

The verifier made 460 decisions, accepted 140 occurrences, and scheduled 138
unique cards. The result passed unknown-word progression, contained no duplicate
sentences, had 97.1% lemma diversity, limited katakana targets to 2.9%, and
represented all ten episodes. It also removed or replaced reported cards 68,
69, and 78. It did not solve the duplicate-learning-unit issue on card 40 or the
audio issue on card 56, which belong to separate gates.

The decision is **fail closed**: 138 usable cards is below the requested 200, so
the universal verifier is not adopted and the frozen baseline remains the
production default. The next experiment should calibrate a risk router that
allows deterministic clean cards through while requiring constrained model
review for ambiguous sense, expression, or subtitle-alignment cases. Exact
metrics and the pinned model revision are recorded in
`qwen35-4b-prompt-v1-regression.json`.
