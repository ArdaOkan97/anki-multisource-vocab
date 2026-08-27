---
id: VOCAB-2.3
title: Fix unknown-context accounting for compounds
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
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Ensure compounds and overlapping expression analyses cannot hide untaught vocabulary from the progressive unknown-word gate.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Card 69 does not report zero unknowns when neither 官 nor 試験官 has been taught
- [ ] #2 A compound is counted as one taught whole unit or by its untaught lexical components, never silently omitted
- [ ] #3 Regression tests cover 試験官 and overlapping expression spans
- [ ] #4 The first-20 and first-200 hard unknown limits still hold
<!-- AC:END -->
