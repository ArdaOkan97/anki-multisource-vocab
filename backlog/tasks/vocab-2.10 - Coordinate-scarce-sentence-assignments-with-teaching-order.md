---
id: VOCAB-2.10
title: Coordinate scarce sentence assignments with teaching order
status: Done
assignee:
  - '@codex'
created_date: '2026-09-05 06:19'
updated_date: '2026-09-05 22:19'
labels: []
dependencies:
  - VOCAB-2.9
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Avoid greedy sentence reservations blocking teachable targets. Preserve multiple candidates per meaning; reconsider earlier assignments while respecting unique examples and staged unknown limits. Investigate 誰, お前 and 君 shared examples, and distinguish rejected from unreviewed alternatives.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Synthetic scarce-example cases teach additional targets by reassignment without reusing sentences
- [x] #2 Every scheduled card satisfies unknown-count limits using only meanings learned earlier
- [x] #3 Failed candidates retry alternatives and bounded search reports unresolved dependencies without relaxing quality gates
- [x] #4 Small A/B reports yield, teaching order and quality against current scheduling
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace deferred equivalence dependency with completed contextual dependency accounting; preserve exact-sense identities. 2. Add bounded sentence reassignment over already validated alternatives, replaying the full greedy scheduler so prior-known-only unknown limits and quality decisions remain enforced. Retain the existing greedy strategy for A/B and fall back without losing previously teachable targets. 3. Expose search bounds, sentence conflicts, unreviewed alternatives and unresolved dependencies; let review planning consider needed replacement examples. 4. Test scarce examples, chained reassignments, failed/unreviewed alternatives and staged limits. Run a small saved-evidence HxH A/B with no local model inference, report honest yield and limits, and create a separate scheduling PR.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented bounded reassignment (64 replays, depth 3) over accepted alternatives, full initial-known-set sequence replay, exact-sense identity preservation and fallback retaining every baseline target. Review frontier now requests replacement examples for already selected targets holding contested sentences. Twelve scheduling/A-B tests cover one- and two-step gains, prerequisites, rejected/unreviewed candidates, staged limits, deterministic fallback and budget exhaustion. Saved-evidence A/B: current gap tolerance 2.0 gives 113 versus 113; historical gap-disabled replay gives 138 versus 138 and exactly matches prior preview audit-position order. No approved replacement moves exist in cached evidence; 7,227 alternatives are unreviewed. Planner exposes 9 replacement reviews in the default first 40. Structural assertions passed; semantic/audio quality was not newly reviewed, and legacy dependency metadata remains explicitly identified. No local models or downloads were used. See benchmarks/verifier-gold-v1/scheduling-ab.md and compact JSON reports.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Sentence reassignment and replacement-review planning implemented with strict prior-known-only checks and bounded fallback. Synthetic bottlenecks improve from 1 to 2 and 2 to 3 taught targets. Real matched saved-evidence A/B preserves yield and historical 138-card ordering; reviewed alternatives are the next yield bottleneck. Audio integration remains VOCAB-2.11, and deferred cross-sense clustering is not required.
<!-- SECTION:FINAL_SUMMARY:END -->
