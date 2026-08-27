---
id: VOCAB-2.5
title: Benchmark a constrained small local verifier
status: To Do
assignee: []
created_date: '2026-08-27 11:36'
labels: []
dependencies:
  - VOCAB-2.1
references:
  - 'https://github.com/MrLesk/Backlog.md'
documentation:
  - docs/future-app.md
parent_task_id: VOCAB-2
priority: high
type: spike
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Determine whether a 1.5B-4B Japanese-capable local model can replace the slow open-ended Qwen 9B passes for a conservative accepted subset using dictionary-grounded multiple-choice decisions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Sense selection uses only surviving JMdict choices plus an explicit none-or-ambiguous option
- [ ] #2 Option order is shuffled and stable sense identity must agree across repeated prompts
- [ ] #3 Subtitle support is checked independently from Japanese sense selection
- [ ] #4 Held-out episodes and a second show report false accepts, coverage, throughput, and memory against the Qwen 9B baseline
- [ ] #5 A smaller model is adopted only when the configured accepted-card precision target is met
<!-- AC:END -->
