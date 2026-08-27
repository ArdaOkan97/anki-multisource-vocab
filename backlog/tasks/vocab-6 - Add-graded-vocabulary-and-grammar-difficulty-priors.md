---
id: VOCAB-6
title: Add graded vocabulary and grammar difficulty priors
status: To Do
assignee: []
created_date: '2026-08-27 11:37'
labels: []
dependencies: []
documentation:
  - README.md
  - docs/future-app.md
priority: low
type: enhancement
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Augment curriculum ranking with optional JLPT or graded-vocabulary levels and grammar familiarity without replacing source frequency or hard comprehensibility gates.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Graded priors are versioned and independently configurable
- [ ] #2 Unseen-card reranking does not disturb existing Anki review history
- [ ] #3 Vocabulary burden and grammar burden are reported separately
- [ ] #4 The frozen baseline can be regenerated with graded priors disabled
<!-- AC:END -->
