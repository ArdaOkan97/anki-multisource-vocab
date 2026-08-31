---
id: VOCAB-2.4
title: Reject contaminated or concatenated subtitle translations
status: Done
assignee:
  - '@codex'
created_date: '2026-08-27 11:29'
updated_date: '2026-08-31 04:23'
labels: []
dependencies:
  - VOCAB-2.1
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/human-review.json
parent_task_id: VOCAB-2
priority: high
type: bug
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Detect English alignments that contain unrelated material even when one clause still expresses the target meaning.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Card 68 is rejected or realigned because its English subtitle includes unrelated prison-sentence text
- [x] #2 Whole-subtitle contamination is evaluated independently from target-sense recoverability
- [x] #3 Deterministic timing and cue-window checks run before any model classifier
- [x] #4 Clean idiomatic translations remain eligible
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Make subtitle alignment conflict-aware: preserve sequential continuation groups, but choose the strongest timing match among mutually overlapping English cue groups instead of concatenating them. 2. Add an explicit deterministic whole-translation-scope criterion that flags structural contamination in already-ingested text independently of target recoverability. 3. Verify deterministic rejection precedes any recorded/model review and add clean idiomatic/multi-cue controls. 4. Run a small frozen-baseline A/B focused on card 68 and curriculum retention.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Real cue inspection found one conflicting English overlay (Sedokan...) substantially overlapping the correct two-cue continuation. Conflict-aware timing selection chooses the correct group and reconstructs 'If we defeat two of the remaining four, then we win.' The existing contaminated database text is independently caught by translation_scope before model reviews. In a 650-target/2,335-candidate A/B, exactly four cards were flagged, all occurrences of the same known-corrupt sentence; the partial 88-card selection retained 0 unknowns through card 20 and <=1 thereafter.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Prevented concatenation of mutually overlapping subtitle layers using timing-first conflict resolution, and added an independent fail-closed translation-scope criterion for already-ingested contamination. Verified card 68 is realigned or rejected, clean sequential and idiomatic translations remain eligible, and 144 tests pass.
<!-- SECTION:FINAL_SUMMARY:END -->
