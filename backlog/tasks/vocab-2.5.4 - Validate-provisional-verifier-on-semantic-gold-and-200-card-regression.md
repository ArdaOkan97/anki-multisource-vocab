---
id: VOCAB-2.5.4
title: Validate provisional verifier on semantic gold and 200-card regression
status: Done
assignee:
  - '@codex'
created_date: '2026-09-03 08:55'
updated_date: '2026-09-05 04:38'
labels: []
dependencies: []
parent_task_id: VOCAB-2.5
priority: high
type: spike
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Determine whether Qwen3.5 4B prompt v1 improves real card and deck quality rather than merely passing a tiny mixed-purpose smoke test. Expand the frozen semantic benchmark with difficult positive and negative cases, keep non-text failures assigned to dedicated gates, and compare an end-to-end episodes 1-10 deck against the frozen 200-card baseline.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The semantic benchmark contains frozen human-gold hard positives, hard negatives, and clean counterexamples, including previously reported contextual-sense failures
- [x] #2 Verifier evaluation reports false accepts, accepted precision, positive coverage, abstentions, and failure categories without charging non-text failures to the text verifier
- [x] #3 The provisional 4B prompt-v1 configuration has zero known semantic false accepts before advancing to end-to-end evaluation
- [x] #4 An episodes 1-10 200-card candidate is compared with the frozen baseline for correctness, usable-card yield, ordering, lexical diversity, duplicate sentences, and unknown-word progression
- [x] #5 The report records an adopt, retain-baseline, or fail-closed decision and preserves existing resource guards
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inventory the existing gold data, frozen baseline artifacts, evaluator, and 200-card comparison tooling. 2. Extend the semantic-gold cohort with representative hard negatives and clean counterexamples while preserving provenance. 3. Run Qwen3.5 4B prompt v1 sequentially under existing memory guards and evaluate semantic precision and coverage. 4. Only if the zero-false-accept gate passes, generate and compare the episodes 1-10 200-card candidate against the frozen baseline. 5. Record the decision, reproducible artifacts, resource usage, and verification evidence.

6. Treat insufficient yield as a candidate-search problem: measure the full occurrence pool, preserve sentence-difficulty ordering per word-sense, advance to the next occurrence after rejection, and avoid relaxing semantic or unknown-word gates.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Semantic gold: Qwen3.5 4B prompt v1 accepted 59/59 semantic cases correctly (0 known semantic false accepts), 59.6% positive coverage, 46 abstentions, 3.171 GiB peak.

End-to-end: searched 7,687 occurrences for 1,500 word-senses. Strict harder-unknown exclusion yielded 112/200; soft difficulty ranking yielded 138/200 after 460 verifier decisions. Unknown-count progression passed, sentences were unique, lemma diversity was 97.1%, katakana ratio 2.9%, and all ten episodes were represented.

Decision: fail closed and retain the frozen baseline. A universal LLM gate is too abstention-heavy; next evaluate a semantic-risk router. Text verification fixed/replaced reported cards 68, 69, and 78, but duplicate-learning-unit card 40 and audio card 56 remain assigned to separate gates.

Final verification: regression evidence consistency script passed; 183 pytest tests passed in 0.97s; both tracked JSON artifacts parse; git diff --check passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Built fingerprinted fail-closed constrained verification and iterative per-word-sense sentence fallback, evaluated pinned Qwen3.5 4B prompt v1 on 105 semantic gold cases and a requested 200-card episodes 1-10 regression, and retained the frozen baseline because exhaustive high-confidence yield stopped at 138 cards. Verified zero known semantic false accepts, resource cleanup under a 3.188 GiB peak, curriculum progression, sentence uniqueness, lexical diversity, episode coverage, and 183 automated tests.
<!-- SECTION:FINAL_SUMMARY:END -->
