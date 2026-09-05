---
id: VOCAB-2.5.5
title: Benchmark contextual sense repair and occurrence equivalence
status: Done
assignee:
  - '@codex'
created_date: '2026-09-05 09:05'
updated_date: '2026-09-05 09:18'
labels: []
dependencies:
  - VOCAB-2.5.4
  - VOCAB-2.9
parent_task_id: VOCAB-2.5
priority: high
type: feature
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Extend the experimental small-model evaluation beyond rejecting the initial dictionary guess. Record alternative dictionary sense selections, independent subtitle support, and same/different/uncertain contextual occurrence decisions. Preserve production defaults and frozen baseline; do not treat implicit card passes or model judgments as explicit semantic gold.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Versioned sense-repair and occurrence-pair cases have stable input fingerprints and explicit review provenance; unlabeled cases never count toward accuracy
- [x] #2 Runner records dictionary-constrained corrected senses and independent subtitle support, and checks equivalence in both occurrence orders without changing production cards
- [x] #3 Evaluation exposes false corrections, false merges, abstentions, coverage and per-split results, with held-out and second-show review gaps explicit
- [x] #4 Tests and reproducible diagnostic queue exercise the new harness while retaining the exclusive local inference memory guard
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add an isolated versioned benchmark module and reproducible unreviewed queues from existing baseline and cross-show artifacts. Enumerate spelling/reading-compatible dictionary senses without the old POS/construction guess. 2. Test sense correction with rotated choices and independent subtitle support, plus symmetric occurrence-equivalence prompts; preserve raw responses and fingerprints. 3. Score only explicit human semantic labels, exposing false repairs/merges, coverage and missing held-out review. 4. Add deterministic harness tests and run a bounded guarded diagnostic if cached model resources permit; keep production and baseline untouched. 5. Record comparative evaluation and independent annotation as the prerequisite for production equivalence changes.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented isolated semantic_benchmark build/run/evaluate module. Reproducible queue: 185 distinct inputs (100 development senses, 40 held-out HxH, 39 second-show, 6 development occurrence pairs); prior implicit labels are intentionally not promoted to semantic gold. 23 new tests cover repair/support separation, label/order changes, provenance, fingerprints, invalid outputs, evaluation, queue deduplication and guarded CLI cleanup. Full suite: 230 passed. Sequential offline eight-case probes: pinned 2B 30.78s / 2.479 decimal GB MLX peak, pinned 4B 80.02s / 3.486 GB peak, both cleanup completed under 4 GiB limit. No empirical accuracy claim: zero independently labeled new cases; 4B same judgment for referential/reaction あれ is a diagnostic warning. Production and frozen baseline unchanged. VOCAB-2.5.6 tracks independent semantic labeling and broader comparison; VOCAB-2.7 depends on it.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Delivered versioned dictionary-grounded sense-repair and occurrence-equivalence benchmark, documented reproducible queues and bounded 2B/4B diagnostics. Verified 230 tests and both guarded model runs; no production adoption or global sense merging. Independent held-out and cross-show semantic evaluation remains VOCAB-2.5.6.
<!-- SECTION:FINAL_SUMMARY:END -->
