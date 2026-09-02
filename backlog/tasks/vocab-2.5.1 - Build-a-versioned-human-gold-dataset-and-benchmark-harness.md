---
id: VOCAB-2.5.1
title: Build a versioned human-gold dataset and benchmark harness
status: To Do
assignee:
  - '@codex'
created_date: '2026-09-02 07:29'
labels: []
dependencies: []
parent_task_id: VOCAB-2.5
priority: high
type: feature
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create a durable, model-independent evaluation foundation for vocabulary-card verification. Replace unsafe or circular LLM teacher labels with versioned human ground truth, preserve frozen development and held-out splits across Hunter x Hunter and a second show, include representative hard negatives, and provide a reproducible harness that evaluates selective acceptance rather than generic model accuracy.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Gold records identify the card, correct JMdict sense or none/ambiguous, subtitle-support judgment, production accept/reject judgment, reason category, reviewer provenance, and schema version
- [ ] #2 Existing human-reviewed HxH feedback is imported without silently changing its decisions, and development, held-out HxH, second-show, and hard-negative splits are deterministic and frozen
- [ ] #3 Hard negatives cover wrong senses, nearby but incorrect subtitles, larger expressions, homographs or alternate readings, fragments, slang, and one-word sentences
- [ ] #4 The harness runs identical versioned prompts and acceptance rules for every candidate and reports false accepts, accepted precision with confidence bounds, coverage, abstentions, option-order stability, invalid outputs, throughput, and peak memory
- [ ] #5 The harness emits machine-readable JSON plus a blinded HTML review artifact and refuses to claim the production precision target when the labeled accepted sample is insufficient
- [ ] #6 No LLM output is treated as gold truth, and all local inference routes through the single-process memory guard
- [ ] #7 Automated tests cover dataset validation, split stability, metric calculation, insufficient-evidence behavior, and report generation
<!-- AC:END -->
