---
id: VOCAB-2.5.3
title: Strengthen and A/B test constrained verifier prompts
status: Done
assignee:
  - '@codex'
created_date: '2026-09-03 07:14'
updated_date: '2026-09-03 08:40'
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

5. Test the strongest currently available 4B MLX candidate that remains inside the 3.5 GiB artifact and 4 GiB runtime guards; compare its prompt-v2 semantic smoke result before deciding whether to expand the cohort.

6. With explicit one-time authorization, run the historical 9B model sequentially on ten cards under a 9 GiB MLX limit, verify cleanup, compare v1 and v2 against the safe 4B result on identical cases, then restore the default 9B block.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented an opt-in prompt v2 while preserving prompt v1 as the CLI default. Added an explicit evaluator override for prompt-only A/B tests that cannot change the acceptance-policy version, and added semantic-gate metrics so audio/curriculum failures are not misattributed to the text verifier. Sequential guarded v1/v2 smoke reruns completed for all four pinned models; every peak stayed below 2.7 GiB. Qwen3.5 v2 improved semantic precision from 6/7 to 7/7 accepted and coverage from 6/14 to 7/14, but slowed from 0.868 to 0.503 cards/s; the cohort is too small for adoption. Gemma and Qwen3 1.7B gained semantic false accepts, while Phi remained nonviable. Verification: 174 tests passed, git diff --check passed, and prompt-v2-ab.json parsed successfully.

Follow-up requested: establish what quality is achievable without reopening the unsafe 9B path. Qwen3.5 4B MLX 4-bit is approximately 3.06 GB and fits the existing artifact ceiling; the approximately 4.04 GB OptiQ variant does not.

Safe quality-ceiling follow-up: pinned Qwen3.5 4B MLX 4-bit revision 32f3e8ecf65426fc3306969496342d504bfa13f3. Prompt v1 accepted 10/14 semantic positives with 10/10 semantic precision, one option-order disagreement, 0 invalid outputs, 0.322 cards/s, 2.706 GiB peak, and a 2.851 GiB artifact. Prompt v2 accepted 8/14 with the same zero semantic false accepts but only 0.193 cards/s and 2.888 GiB peak. All four production-label false accepts under v1 were outside the text verifier's scope: audio overlap, two duplicate-learning-unit cases, and compound unknown-word accounting. Conclusion: 4B plus prompt v1 is the strongest safe candidate; expand semantic hard-negative gold before adoption.

Explicitly authorized isolated 9B exception completed sequentially on a balanced 10-card smoke subset under a 9 GiB MLX limit. Prompt v1: 6 semantic true accepts, 1 semantic false accept, 0.155 cards/s, and 7.440 GiB peak. Prompt v2: 4 semantic true accepts, zero semantic false accepts, 0.097 cards/s, and 7.547 GiB peak. Cleanup was verified after both runs with no overlapping inference process. On the identical cases, safe 4B prompt v1 produced 5/5 semantic accepted precision versus 9B prompt v2's 4/4, so 9B did not beat 4B and remains blocked by default.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed the explicitly authorized isolated 9B comparison without weakening production resource guards. The 9B model did not outperform safe Qwen3.5 4B prompt v1, so the 4B result remains the quality ceiling and 9B remains blocked. Updated the benchmark report and verified 174 tests, JSON validity, diff cleanliness, and process cleanup.
<!-- SECTION:FINAL_SUMMARY:END -->
