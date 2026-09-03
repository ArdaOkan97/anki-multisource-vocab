---
id: VOCAB-2.5.3
title: Strengthen and A/B test constrained verifier prompts
status: Done
assignee:
  - '@codex'
created_date: '2026-09-03 07:14'
updated_date: '2026-09-03 07:31'
labels: []
dependencies: []
parent_task_id: VOCAB-2.5
priority: high
type: spike
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Determine whether clearer fail-closed instructions improve small local verifier compliance and semantic precision without changing models, datasets, decoding, resource limits, or acceptance policy. Preserve prompt v1 as the regression baseline and compare a versioned prompt v2 on the same smoke cohort.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Prompt v1 remains reproducible and prompt v2 is separately versioned
- [x] #2 The same pinned models, 20 gold cases, decoding settings, and memory guard are used for the A/B comparison
- [x] #3 Results report raw-output compliance, semantic decisions, false accepts, and coverage for both prompts
- [x] #4 Production behavior is not changed unless prompt v2 materially improves relevant semantic metrics without new false accepts
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a versioned prompt-policy selector while preserving v1 byte-for-byte. 2. Add prompt-v2 tests covering strict output format, context-only sense selection, ambiguity, expression boundaries, and translation contamination. 3. Run the guarded 20-card smoke A/B sequentially on the existing local model artifacts. 4. Compare per-gate semantic outcomes separately from unrelated production failures and recommend retain or adopt.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented an opt-in prompt v2 while preserving prompt v1 as the CLI default. Added an explicit evaluator override for prompt-only A/B tests that cannot change the acceptance-policy version, and added semantic-gate metrics so audio/curriculum failures are not misattributed to the text verifier. Sequential guarded v1/v2 smoke reruns completed for all four pinned models; every peak stayed below 2.7 GiB. Qwen3.5 v2 improved semantic precision from 6/7 to 7/7 accepted and coverage from 6/14 to 7/14, but slowed from 0.868 to 0.503 cards/s; the cohort is too small for adoption. Gemma and Qwen3 1.7B gained semantic false accepts, while Phi remained nonviable. Verification: 174 tests passed, git diff --check passed, and prompt-v2-ab.json parsed successfully.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added and benchmarked a stronger constrained verifier prompt without changing the production default. Prompt v2 improved Qwen3.5's 20-case semantic result but lacks enough accepted gold evidence and is slower, so v1 remains the baseline. Results and per-gate metrics are reproducible and documented; 174 tests pass.
<!-- SECTION:FINAL_SUMMARY:END -->
