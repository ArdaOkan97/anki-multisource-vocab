---
id: VOCAB-2.6
title: Resolve construction-level senses and semantic duplicates
status: To Do
assignee: []
created_date: '2026-08-27 11:36'
labels: []
dependencies:
  - VOCAB-2.1
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/human-review.json
parent_task_id: VOCAB-2
priority: high
type: bug
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Prevent compositional grammar constructions from being assigned an incompatible ordinary dictionary sense or taught twice under technically different sense IDs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Card 78 maps 答えてくれ to the benefactive or request use already represented by card 58
- [ ] #2 The ordinary give sense is rejected for verb-te plus くれる request constructions
- [ ] #3 Genuinely distinct source-attested senses remain independently learnable
- [ ] #4 Regression tests cover くれる, そう, どうも, and other existing expression cases
<!-- AC:END -->
