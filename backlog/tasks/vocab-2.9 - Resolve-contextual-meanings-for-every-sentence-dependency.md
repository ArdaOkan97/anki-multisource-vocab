---
id: VOCAB-2.9
title: Resolve contextual meanings for every sentence dependency
status: Done
assignee:
  - '@codex'
created_date: '2026-09-05 06:19'
updated_date: '2026-09-05 08:44'
labels: []
dependencies:
  - VOCAB-2.8
parent_task_id: VOCAB-2
priority: high
type: bug
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Unknown-word accounting must reflect meanings used in the sentence, not merely previously seen spellings. Card 21 currently treats 何で meaning why as previously learned 何 meaning what. Resolve context expressions and senses conservatively without show-specific exceptions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Learning 何 or 何だ does not automatically mark the why usage of 何で as known
- [x] #2 Regression cases cover target and non-target expressions, compositional alternatives, and ambiguous context
- [x] #3 Unknown counts and progression gates use the same occurrence-level meaning identities as teaching
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Use stored expression decisions for every sentence dependency: accepted expressions stay atomic, resolved components stay separate, and ambiguous/insufficient-evidence spans become explicitly unresolved dependencies instead of inheriting component mastery.
2. Share occurrence-level identities between candidate targets and context accounting; reject stale target identities or targets intersecting unresolved meanings. Preserve metadata for audit explanations, and keep unresolved identities out of the simulated learned set.
3. Add regressions for 何で, other expressions, compositional counterexamples, overlapping spans, target and non-target uses, and previously learned components.
4. Run a read-only small A/B on current selected examples and record corrections without reimporting, model inference, changing thresholds, or overwriting the frozen baseline. Create a separate PR.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented versioned occurrence dependency spans and dictionary-backed missing-analysis detection without new inference. Accepted expressions and resolved components remain distinct; unresolved expression spans no longer inherit mastery. Deterministic and scheduling gates validate target/context agreement and reject stale accepted results with unresolved context.
Read-only paired A/B of 138 selected cards: 24 have unresolved context, 114 unchanged. Card21 changes from 1 to 2 other unknown meanings. These are uncertainty flags, not 24 proven translation errors. No source DB or frozen baseline writes.
207 tests passed, including broad expression/overlap cases, target mismatch, legacy missing analyses, cache isolation and read-only enforcement. Added reproducible comparison script and benchmark notes. Also fixed the existing soft-hardness None diagnostic crash exercised by deferred accepted examples.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Context accounting now preserves unresolved expression meanings across the whole sentence instead of inheriting learned components. Added exact target/context checks, legacy analysis safeguards and read-only A/B tooling. Verified 207 tests and the reported 何で card changing from one to two unknown meanings; no models or thresholds changed.
<!-- SECTION:FINAL_SUMMARY:END -->
