---
id: VOCAB-2.5.1
title: Build a versioned human-gold dataset and benchmark harness
status: Done
assignee:
  - '@codex'
created_date: '2026-09-02 07:29'
updated_date: '2026-09-02 08:02'
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
- [x] #1 Gold records identify the card, correct JMdict sense or none/ambiguous, subtitle-support judgment, production accept/reject judgment, reason category, reviewer provenance, and schema version
- [x] #2 Existing human-reviewed HxH feedback is imported without silently changing its decisions, and development, held-out HxH, second-show, and hard-negative splits are deterministic and frozen
- [x] #3 Hard negatives cover wrong senses, nearby but incorrect subtitles, larger expressions, homographs or alternate readings, fragments, slang, and one-word sentences
- [x] #4 The harness runs identical versioned prompts and acceptance rules for every candidate and reports false accepts, accepted precision with confidence bounds, coverage, abstentions, option-order stability, invalid outputs, throughput, and peak memory
- [x] #5 The harness emits machine-readable JSON plus a blinded HTML review artifact and refuses to claim the production precision target when the labeled accepted sample is insufficient
- [x] #6 No LLM output is treated as gold truth, and all local inference routes through the single-process memory guard
- [x] #7 Automated tests cover dataset validation, split stability, metric calculation, insufficient-evidence behavior, and report generation
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Define and validate a versioned model-independent gold/review-queue schema.
2. Import the frozen HxH human decisions, deterministic held-out HxH and second-show queues, and representative synthetic hard negatives.
3. Add benchmark evaluation metrics, confidence-bound gating, and blinded HTML/JSON reports.
4. Expose dataset-build, guarded run, and benchmark-evaluate CLI commands.
5. Add automated coverage, generate the committed v1 artifact, and verify task acceptance criteria.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented a versioned gold/review-queue schema and generated verifier-gold-v1: 100 human-reviewed development cases (95 implicit passes, 5 preserved explicit rejects), deterministic 40-card held-out HxH and 40-card second-show queues marked unreviewed, and 5 transparent hard negatives. Added guarded dataset inference, prompt/rule version enforcement, selective-acceptance metrics with Wilson confidence bounds and minimum-sample refusal, JSON plus blinded HTML reports, and CLI commands. No model inference was run. Full suite: 160 passed.

Final verification: jq schema/decision/split/tag invariants passed; dataset SHA-256 cfa4618795567edd9f2358ce72c1d667ba56da8961a962c93e93c968a74472a2; both run/evaluate CLI entry points load; git diff --check passed; full test suite 160 passed in 1.28s.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Built verifier-gold-v1 and a guarded, version-locked benchmark workflow. Human decisions remain distinct from unlabeled queues and synthetic negatives; evaluation reports selective-acceptance quality and fails closed on insufficient evidence. Verified with dataset invariants, CLI smoke checks, diff validation, and 160 automated tests.
<!-- SECTION:FINAL_SUMMARY:END -->
