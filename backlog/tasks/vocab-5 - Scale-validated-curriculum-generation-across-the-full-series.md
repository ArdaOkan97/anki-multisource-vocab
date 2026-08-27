---
id: VOCAB-5
title: Scale validated curriculum generation across the full series
status: To Do
assignee: []
created_date: '2026-08-27 11:37'
labels: []
dependencies:
  - VOCAB-2
priority: medium
type: feature
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Generate cumulative Hunter x Hunter learning batches across all episodes after the reliability initiative is complete, starting with 200 words for episodes 1-10 and adding 100 per subsequent ten-episode block.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Each episode block records which sources were already consumed
- [ ] #2 Global learning-unit deduplication prevents relearning the same validated meaning across blocks and shows
- [ ] #3 Every batch uses the same fail-closed gates and produces an A/B quality report
- [ ] #4 Generation time, accepted coverage, and deferred reasons are reported for the full series
<!-- AC:END -->
