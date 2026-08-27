---
id: VOCAB-7
title: Build an Anki source-switcher companion add-on
status: To Do
assignee: []
created_date: '2026-08-27 11:37'
labels: []
dependencies: []
documentation:
  - README.md
priority: low
type: feature
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Provide an Anki-side companion that synchronizes learned state and switches active source queues without requiring manual CLI commands after reviews.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The add-on refreshes global learned state before filling a source queue
- [ ] #2 Switching shows never creates a duplicate learned learning unit
- [ ] #3 Reviewed cards remain in their original decks
- [ ] #4 Failures leave Anki and the SQLite source of truth in a recoverable state
<!-- AC:END -->
