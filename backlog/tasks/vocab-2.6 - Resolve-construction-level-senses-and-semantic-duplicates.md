---
id: VOCAB-2.6
title: Resolve construction-level senses and semantic duplicates
status: Done
assignee:
  - '@codex'
created_date: '2026-08-27 11:36'
updated_date: '2026-09-02 08:38'
labels: []
dependencies:
  - VOCAB-2.1
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/human-review.json
parent_task_id: VOCAB-2
priority: high
type: bug
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Prevent compositional grammar constructions from being assigned an incompatible ordinary dictionary sense or taught twice under technically different sense IDs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Card 78 maps 答えてくれ to the benefactive or request use already represented by card 58
- [x] #2 The ordinary give sense is rejected for verb-te plus くれる request constructions
- [x] #3 Genuinely distinct source-attested senses remain independently learnable
- [x] #4 Regression tests cover くれる, そう, どうも, and other existing expression cases
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Trace expression analysis, sense selection, and learning-unit deduplication for card 78 and existing そう/どうも cases.
2. Add a general construction-level interpretation layer that can override incompatible component senses without collapsing unrelated source-attested meanings.
3. Feed construction identities into candidate validation and semantic deduplication.
4. Add focused regressions for Vてくれる requests, そう, どうも, and existing expression fixtures.
5. Regenerate the relevant baseline comparison, run the full suite, and package a separate PR.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented a target-span-aware construction rule for auxiliary くれる after verb て/で forms. It selects JMdict 1269130 sense 2 for both card 58 and card 78, filters the incompatible ordinary-give sense from constrained choices, and leaves standalone 金をくれ on sense 0. Bumped dictionary resolver version to 6 so stored occurrence senses refresh. Added resolver, constrained-choice, database learning-unit, and frozen baseline comparison regressions; existing distinct そう and opaque どうも tests remain green. Full suite: 169 passed.

Final verification: construction comparison invariant passed, git diff --check passed, and full suite completed with 169 passing tests.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added target-span-aware Vて/で＋くれる sense resolution and propagated it through occurrence enrichment, constrained choices, and learning-unit identity. Card 78 now deduplicates with card 58, ordinary give remains distinct, and existing そう/どうも expression behavior is preserved. Verified with a frozen before/after artifact and 169 tests.
<!-- SECTION:FINAL_SUMMARY:END -->
