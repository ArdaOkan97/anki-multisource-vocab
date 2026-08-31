---
id: VOCAB-2.3
title: Fix unknown-context accounting for compounds
status: Done
assignee:
  - '@codex'
created_date: '2026-08-27 11:29'
updated_date: '2026-08-31 04:17'
labels: []
dependencies:
  - VOCAB-2.1
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/human-review.json
parent_task_id: VOCAB-2
priority: high
type: bug
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Ensure compounds and overlapping expression analyses cannot hide untaught vocabulary from the progressive unknown-word gate.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Card 69 does not report zero unknowns when neither 官 nor 試験官 has been taught
- [x] #2 A compound is counted as one taught whole unit or by its untaught lexical components, never silently omitted
- [x] #3 Regression tests cover 試験官 and overlapping expression spans
- [x] #4 The first-20 and first-200 hard unknown limits still hold
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Materialize conservative context dependencies from current lexical tokenization in addition to persisted occurrence senses, preserving accepted whole-expression units while exposing any uncovered components. 2. Make curriculum planning resolve each context group as a known whole when available, otherwise count its untaught lexical components, and fail closed for unscored dependencies. 3. Add regressions for 試験官/官 and overlapping expression spans. 4. Run focused tests plus frozen-baseline A/B checks for first-20/first-200 unknown limits.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed the frozen card-69 sentence stored 俺, 本物, and 試験 but omitted current-tokenizer suffix 官. Added conservative retokenization for context dependencies: persisted sense-aware spans remain atomic, while uncovered current lexical tokens receive stable sense-aware dependency keys. A 650-target A/B candidate run now includes 官 (jmdict:1983700:0) for that sentence; the partial 88-card selection preserves 0 unknowns through card 20 and <=1 through card 200.

Final verification: 141 pytest tests passed. The real HxH candidate sentence now contains 官 as context dependency 14b5e640736cd04cc3b51b53::jmdict:1983700:0. Regression tests prove a known 試験 prefix still leaves 官 as exactly one unknown and that a persisted whole 試験官 span supersedes its nested 試験 component. The 88-card small A/B selection has max unknowns 0 through card 20 and 1 thereafter.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Made context dependency accounting fail closed across tokenizer versions: sense-aware persisted whole spans remain atomic, nested component spans are suppressed, partially overlapping spans remain visible, and uncovered current lexical components are restored. Verified against the real 試験官 card, a small frozen-baseline A/B selection, and 141 passing tests.
<!-- SECTION:FINAL_SUMMARY:END -->
