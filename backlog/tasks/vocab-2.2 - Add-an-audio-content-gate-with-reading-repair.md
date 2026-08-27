---
id: VOCAB-2.2
title: Add an audio-content gate with reading repair
status: To Do
assignee: []
created_date: '2026-08-27 11:29'
labels: []
dependencies:
  - VOCAB-2.1
documentation:
  - docs/future-app.md
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Validate that authentic source audio contains the target reading, has usable boundaries, and is not dominated by competing speech. Repair a displayed reading when one compatible dictionary alternative is uniquely supported.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Card 56 is rejected, re-cut, or replaced when its clip contains unusable competing speech
- [ ] #2 The 誰だ お前 clip expands when the target lies beyond the original cue tail
- [ ] #3 次は私だ selects わたし instead of わたくし when audio evidence is decisive
- [ ] #4 Ambiguous reading or speaker evidence fails closed and all repairs are audited and revalidated
<!-- AC:END -->
