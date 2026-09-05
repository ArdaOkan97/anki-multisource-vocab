---
id: VOCAB-2.5.6
title: Evaluate sense repair and equivalence on independently labeled cases
status: In Progress
assignee:
  - '@codex'
created_date: '2026-09-05 09:06'
updated_date: '2026-09-05 09:50'
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
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
User explicitly requested testing the three earlier verifier candidates on the new equivalence/sense-repair diagnostic. This is an initial slice of the task, not completion of the independent-gold acceptance criteria.

Completed user-requested additional eight-case diagnostics with unchanged prompts/parser/options. Sequential offline cached runs under exclusive 4 GiB MLX cap: Gemma 2B Japanese 26.07s / 2.206 GB peak, six same pair decisions (including concerning are pair), two sense order disagreements; Qwen3 1.7B 28.61s / 1.719 GB, six invalid-format pair abstentions plus two sense order disagreements; Phi-4 Mini 37.77s / 3.187 GB, eight invalid-format abstentions. All cleanup completed; fingerprint evaluation passed. Qwen/Phi often echo option text, so format failures are not proof of semantic inability; parser was not relaxed post hoc. No new gold labels, no adoption, no production changes. Evidence and reproduction: benchmarks/verifier-gold-v1/semantic-repair-additional-models.md. Broader independent-label acceptance criteria remain unchecked.
<!-- SECTION:NOTES:END -->
