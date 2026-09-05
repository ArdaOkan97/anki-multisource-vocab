---
id: VOCAB-2.10
title: Coordinate scarce sentence assignments with teaching order
status: To Do
assignee: []
created_date: '2026-09-05 06:19'
labels: []
dependencies:
  - VOCAB-2.7
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Avoid greedy sentence reservations blocking teachable targets. Preserve multiple candidates per meaning; reconsider earlier assignments while respecting unique examples and staged unknown limits. Investigate 誰, お前 and 君 shared examples, and distinguish rejected from unreviewed alternatives.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Synthetic scarce-example cases teach additional targets by reassignment without reusing sentences
- [ ] #2 Every scheduled card satisfies unknown-count limits using only meanings learned earlier
- [ ] #3 Failed candidates retry alternatives and bounded search reports unresolved dependencies without relaxing quality gates
- [ ] #4 Small A/B reports yield, teaching order and quality against current scheduling
<!-- AC:END -->
