---
id: VOCAB-2.9
title: Resolve contextual meanings for every sentence dependency
status: To Do
assignee: []
created_date: '2026-09-05 06:19'
labels: []
dependencies:
  - VOCAB-2.8
parent_task_id: VOCAB-2
priority: high
type: bug
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Unknown-word accounting must reflect meanings used in the sentence, not merely previously seen spellings. Card 21 currently treats 何で meaning why as previously learned 何 meaning what. Resolve context expressions and senses conservatively without show-specific exceptions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Learning 何 or 何だ does not automatically mark the why usage of 何で as known
- [ ] #2 Regression cases cover target and non-target expressions, compositional alternatives, and ambiguous context
- [ ] #3 Unknown counts and progression gates use the same occurrence-level meaning identities as teaching
<!-- AC:END -->
