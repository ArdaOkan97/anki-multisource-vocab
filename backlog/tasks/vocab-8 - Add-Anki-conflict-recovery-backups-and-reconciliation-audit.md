---
id: VOCAB-8
title: 'Add Anki conflict recovery, backups, and reconciliation audit'
status: To Do
assignee: []
created_date: '2026-08-27 11:37'
labels: []
dependencies:
  - VOCAB-7
documentation:
  - README.md
priority: low
type: feature
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Detect and recover from cards manually deleted, moved, edited, or merged inside Anki while protecting review history and the global learning dictionary.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A dry-run audit reports conflicts before mutation
- [ ] #2 Backups are created before reconciliation changes
- [ ] #3 Reviewed cards are never silently deleted or reassigned
- [ ] #4 Recovery behavior is covered for deleted, moved, edited, and duplicate notes
<!-- AC:END -->
