---
id: VOCAB-2.1
title: Build baseline A/B comparison reports
status: To Do
assignee: []
created_date: '2026-08-27 11:29'
labels: []
dependencies: []
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/config.json
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Compare any candidate selection with the frozen 200-card snapshot and produce a reviewable report before changing production defaults.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The report shows retained, removed, added, reordered, and learner-visible changed cards
- [ ] #2 The report separately identifies reading, sense, gloss, sentence, translation, audio, and unknown-count changes
- [ ] #3 The report checks the five first-half human findings and the curriculum unknown-word invariants
- [ ] #4 Machine-readable JSON and a human-readable HTML or Markdown report are produced
<!-- AC:END -->
