---
id: VOCAB-2.5.6
title: Evaluate sense repair and equivalence on independently labeled cases
status: In Progress
assignee:
  - '@codex'
created_date: '2026-09-05 09:06'
updated_date: '2026-09-05 11:26'
labels: []
dependencies:
  - VOCAB-2.5.5
parent_task_id: VOCAB-2.5
priority: high
type: spike
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Use the new semantic-repair/equivalence harness to compare the pinned provisional Qwen3.5 4B and cached 2B candidate under identical prompts. Evaluate real contextual decisions, not blanket rejection. Existing implicit baseline passes and model judgments are not independent gold for these new labels.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Explicit semantic review labels cover correct and incorrect initial guesses, equivalent and distinct occurrences, uncertainty, held-out words/episodes and a second show, with reviewer provenance
- [ ] #2 Sequential memory-guarded matched runs report false repairs, false merges, retained distinctions, abstentions, coverage, throughput and peak memory per split
- [ ] #3 Recommendation states uncertainty and measured tradeoffs; production adoption requires sufficient independent evidence and a deck-level A/B with the frozen baseline
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend the identical eight-case diagnostic to the previously cached Gemma 2 2B Japanese, Qwen3 1.7B and Phi-4 Mini revisions requested by the user. 2. Run one offline process at a time under the existing exclusive 4 GiB MLX guard; preserve raw outputs and record cleanup, time and peak memory. 3. Compare observed decisions with the existing 2B/4B runs without claiming accuracy from unreviewed cases. 4. Keep independent semantic annotation and held-out/cross-show evaluation pending before any production decision.

5. User-approved simplification experiment: compare only lemma and two recorded dictionary glosses (no sentences, JSON, offsets or full option inventories), using the same five cached models and unchanged strict output parser/decoding. Rotate labels and reverse meaning order; include identical-gloss sanity controls. Treat this as a distinct dictionary-equivalence task, not a causal A/B or gold-scored contextual evaluation. Preserve raw runs and production defaults.

6. User-approved English embedding alternative: benchmark pinned all-mpnet-base-v2, bge-base-en-v1.5 and bge-large-en-v1.5 against multilingual-e5-small on the same definition pairs plus transparent paraphrase/related-but-distinct diagnostics. Use symmetric model-appropriate inputs, cache normalized vectors, report cosine scores without adopting a threshold. Download only required weights, run CPU-only in separate sequential processes with small batches and a monitored 4 GiB RSS ceiling sharing the inference lock. Keep labels explicitly provisional and no gold-calibrated threshold claim.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
User explicitly requested testing the three earlier verifier candidates on the new equivalence/sense-repair diagnostic. This is an initial slice of the task, not completion of the independent-gold acceptance criteria.

Completed user-requested additional eight-case diagnostics with unchanged prompts/parser/options. Sequential offline cached runs under exclusive 4 GiB MLX cap: Gemma 2B Japanese 26.07s / 2.206 GB peak, six same pair decisions (including concerning are pair), two sense order disagreements; Qwen3 1.7B 28.61s / 1.719 GB, six invalid-format pair abstentions plus two sense order disagreements; Phi-4 Mini 37.77s / 3.187 GB, eight invalid-format abstentions. All cleanup completed; fingerprint evaluation passed. Qwen/Phi often echo option text, so format failures are not proof of semantic inability; parser was not relaxed post hoc. No new gold labels, no adoption, no production changes. Evidence and reproduction: benchmarks/verifier-gold-v1/semantic-repair-additional-models.md. Broader independent-label acceptance criteria remain unchecked.

Completed approved word-and-two-glosses probe with identical strict parser and decoding, six original dictionary pairs plus two identical-gloss controls. Five sequential offline runs completed under 4 GiB MLX guard: Qwen3.5 2B 6.21s/1.691 GB, 4B 13.64s/2.627 GB, Gemma 6.07s/1.608 GB, Qwen3 1.7B 5.70s/1.149 GB, Phi 8.44s/2.348 GB. All pair hashes matched; cleanup completed. Both Qwen3.5 models now distinguish the are definitions, but identical-gloss control passes were 1/2 for 2B and 0/2 for 4B; Gemma passed 2/2 but answered same for five non-control pairs. Qwen1.7/Phi still had extra-text formatting failures. This changes the semantic question, so it is not a controlled contextual-prompt A/B or gold accuracy test. No production changes. Exact prompts/results: benchmarks/verifier-gold-v1/simple-dictionary-pairs.md. Added nine tests; full suite 239 passed.

Completed approved CPU-only definition embedding comparison: pinned multilingual-e5-small, all-mpnet-base-v2, bge-base-en-v1.5 and bge-large-en-v1.5, 20 identical pair inputs / 34 definition strings per model. English-only alternatives tested with plain symmetric inputs; E5 uses query prefix on both sides, not production query/passage scoring. Sequential shared-lock runs, batch four, two CPU threads, monitored 4 GiB RSS ceiling; measured peaks 1.006/0.820/0.817/1.621 GiB. Load+encode 1.88/0.67/1.15/3.74s excluding download/import. Every identical control scored 1.0. All models have overlapping paraphrase/related-distinct ranges (BGE-large lend/borrow .956 versus buy/purchase .962; MPNet lend/borrow .797 versus begin/commence .648). No threshold tuned or adopted; no independent gold claims. Nine added tests, full suite 248 passed. Evidence and reproduction: benchmarks/verifier-gold-v1/embedding-pairs.md. Production and frozen baseline unchanged.
<!-- SECTION:NOTES:END -->
