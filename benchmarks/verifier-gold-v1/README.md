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
