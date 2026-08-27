---
id: VOCAB-2.4
title: Reject contaminated or concatenated subtitle translations
status: To Do
assignee: []
created_date: '2026-08-27 11:29'
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
- [ ] #1 Card 68 is rejected or realigned because its English subtitle includes unrelated prison-sentence text
- [ ] #2 Whole-subtitle contamination is evaluated independently from target-sense recoverability
- [ ] #3 Deterministic timing and cue-window checks run before any model classifier
- [ ] #4 Clean idiomatic translations remain eligible
<!-- AC:END -->
