# Word-and-two-meanings probe (2026-09-05)

User-approved simplification within VOCAB-2.5.6. This is **dictionary meaning
equivalence**, not contextual occurrence equivalence. There are no sentences,
translations, offsets, JSON or full dictionary lists in the prompt. Definitions
are copied from the two originally selected sense keys in the frozen options;
they are not assumed to be correct for the source occurrences.

The exact first-pass prompt for あれ is:

```text
Word: あれ
Meaning 1: that; that thing
Meaning 2: huh?; eh?; what?

Do these meanings describe the same use of this word?

A. Equivalent
B. Different
C. Unsure

Answer with one letter.
```

The second pass reverses meaning order and rotates choices to A=Different,
B=Unsure, C=Equivalent. It tests joint order sensitivity, not which of these two
changes causes a disagreement. The six original pairs are supplemented with
two identical-definition controls: 何 (what / what) and あれ (that; that thing /
that; that thing). Those controls are structural sanity checks, not an expanded
independently annotated semantic gold set.

All five cached, pinned models ran sequentially offline, each process exiting
before the next started, under the exclusive 4 GiB MLX guard. The parser and
decoding settings are unchanged: strict one-letter outputs (optional terminal
punctuation and known EOS markers), temperature zero, four-token generation
budget and 1024-token KV limit. Every run made 16 prompt calls and completed
cleanup. Pair hashes matched across models and record fingerprints were checked.

## Results

| Model | Loop time | MLX peak GB | Valid letter responses | Identical controls passed |
| --- | ---: | ---: | ---: | ---: |
| Qwen3.5 2B OptiQ | 6.21 s | 1.691 | 16/16 | 1/2 |
| Qwen3.5 4B | 13.64 s | 2.627 | 16/16 | 0/2 |
| Gemma 2 2B Japanese | 6.07 s | 1.608 | 16/16 | 2/2 |
| Qwen3 1.7B | 5.70 s | 1.149 | 6/16 | 0/2 |
| Phi-4 Mini | 8.44 s | 2.348 | 6/16 | 0/2 |

Memory is decimal GB reported by MLX, not total process memory; times exclude
model loading. No production setting or frozen baseline changed.

| Word | Qwen3.5 2B | Qwen3.5 4B | Gemma | Qwen3 1.7B | Phi |
| --- | --- | --- | --- | --- | --- |
| 何 | order disagreement | order disagreement | same | invalid | invalid |
| あれ | different | different | order disagreement | invalid | invalid |
| 分かる | order disagreement | order disagreement | same | order disagreement | invalid |
| こっち | order disagreement | order disagreement | same | invalid | invalid |
| どっち | order disagreement | different | same | invalid | invalid |
| くれる | different | order disagreement | same | invalid | invalid |

Every disagreement/invalid result abstains; only stable mapped answers produce
a relation. Qwen3.5 2B and 4B now distinguish the supplied あれ definitions in
both orders, unlike the earlier contextual probe's 4B `same` result. However,
2B fails one identical-gloss control and 4B fails both by disagreeing across
passes. Gemma passes both controls but labels five of the six distinct-sense
pairs `same`. This does not justify enabling global merges.

Qwen3 1.7B and Phi still echo option text, e.g. `C. Equivalent` or `B. Different`,
which is rejected under the unchanged parser. Formatting failures should not
be scored as proof of semantic inability. No output was retrospectively rescued.

The shorter runs are useful diagnostics, but this is **not a controlled prompt
A/B of the same semantic task**: it compares dictionary meanings rather than
sentence usages, and substitutes two structural controls for the old two sense
selection cases. There are no independent gold-scored accuracy claims. In
particular, two dictionary definitions can be distinct even when an earlier
pipeline assigned one incorrectly to an otherwise redundant occurrence.

## Reproduce

Build the source queue as documented in `semantic-repair.md`. Then, one model
at a time:

```console
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m vocabdeck.dictionary_pair_probe \
  --dataset .vocabdeck/benchmarks/semantic-repair-v1-queue.json \
  --model MODEL --revision REVISION --limit 8 --memory-limit-gb 4 \
  --output .vocabdeck/benchmarks/simple-dictionary-pairs-NAME.json
```

The model IDs and revisions are unchanged from `semantic-repair.md` and
`semantic-repair-additional-models.md`. Local output NAME values are `2b`, `4b`,
`gemma`, `qwen17b`, and `phi`. Each artifact contains the exact two definitions,
source identity, prompts, raw replies, mappings, fingerprints, decisions and
runtime configuration. The script defaults to eight cases and checkpoints after
each pair. Nine added tests cover prompt contents, order changes, structural
controls, strict parsing and checkpointing; the full suite passes 239 tests.

VOCAB-2.5.6 remains in progress: independent semantic labels and held-out/show
coverage are still missing. No model has been selected for production merging.
