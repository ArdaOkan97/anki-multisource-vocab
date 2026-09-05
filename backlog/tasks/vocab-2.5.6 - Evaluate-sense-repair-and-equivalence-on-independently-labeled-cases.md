---
id: VOCAB-2.5.6
title: Evaluate sense repair and equivalence on independently labeled cases
status: To Do
assignee: []
created_date: '2026-09-05 09:06'
labels: []
dependencies:
  - VOCAB-2.5.5
parent_task_id: VOCAB-2.5
priority: high
type: spike
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Use the new semantic-repair/equivalence harness to compare the pinned provisional Qwen3.5 4B and cached 2B candidate under identical prompts. Evaluate real contextual decisions, not blanket rejection. Existing implicit baseline passes and model judgments are not independent gold for these new labels.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Explicit semantic review labels cover correct and incorrect initial guesses, equivalent and distinct occurrences, uncertainty, held-out words/episodes and a second show, with reviewer provenance
- [ ] #2 Sequential memory-guarded matched runs report false repairs, false merges, retained distinctions, abstentions, coverage, throughput and peak memory per split
- [ ] #3 Recommendation states uncertainty and measured tradeoffs; production adoption requires sufficient independent evidence and a deck-level A/B with the frozen baseline
<!-- AC:END -->
