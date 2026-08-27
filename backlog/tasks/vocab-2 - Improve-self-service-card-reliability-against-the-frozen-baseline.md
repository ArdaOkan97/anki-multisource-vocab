---
id: VOCAB-2
title: Improve self-service card reliability against the frozen baseline
status: To Do
assignee: []
created_date: '2026-08-27 11:21'
labels: []
dependencies: []
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/human-review.json
priority: high
type: feature
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Coordinate independently reviewable reliability improvements. Every child task must compare its output with the frozen Hunter x Hunter baseline and preserve the fail-closed curriculum policy.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every completed child task reports baseline-versus-experiment card retention, replacements, and fixed flagged cases
- [ ] #2 Cards 1-20 retain zero other unknown learning units and cards 21-200 retain at most one
- [ ] #3 Uncertain semantic, reading, audio, and alignment evidence fails closed or selects another occurrence
<!-- AC:END -->
