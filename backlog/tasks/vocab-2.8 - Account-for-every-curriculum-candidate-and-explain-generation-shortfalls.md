---
id: VOCAB-2.8
title: Account for every curriculum candidate and explain generation shortfalls
status: Done
assignee:
  - '@codex'
created_date: '2026-09-05 06:18'
updated_date: '2026-09-05 06:29'
labels: []
dependencies: []
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Explain the HxH E1–10 138-card result without treating unreviewed candidates as model rejections. Preserve the frozen baseline and generation decisions; provide reproducible candidate-level and target-level diagnostics.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Every candidate has exactly one primary disposition, with counts reconciling to the complete input pool and distinct sentence and learning-unit totals
- [x] #2 Report review decisions separately from deterministic and scheduling blockers, including unknown dependencies, missing scores, already-taught targets, and sentence reservation owners
- [x] #3 JSON and readable HTML reports explain unresolved targets including 誰, お前 and 君 without invoking inference or changing selection
- [x] #4 Tests cover alternative occurrences, shared sentences, missing metadata, unknown limits, and unreviewed candidates; report documents final-state limitations
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Build a read-only final-state candidate accounting report from existing candidate, validation, and selection artifacts.
2. Preserve independent deterministic, recorded validation, and dependency/sentence-reservation dimensions; choose one documented primary disposition per row.
3. Add a CLI and searchable HTML with per-target summaries, policy values and input hashes. Reject inconsistent inputs rather than silently joining unrelated records.
4. Test reconciliation and eligibility edge cases, then run on the 7687-candidate HxH artifact without inference. Record findings and keep generation behavior unchanged.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Verified the full 7687-pair artifact without inference: 2260 distinct sentences, 1500 units, 138 selected, 460 model reviews (140 accepted / 208 rejected / 112 abstained), 7227 unreviewed. Exclusive categories reconcile exactly. 誰 accepted candidate2092 is reserved by お前 card22; two unreviewed alternatives are reserved by 君 card27 and 行く card24.
196 automated tests pass, including CLI input hashes and non-mutation, HTML escaping, policy parity with the planner, metadata failures and shared sentences. Full JSON/HTML generated at .vocabdeck/audits/hxh-e01-e10-candidate-accounting.*. Browser inspection was blocked by local-file URL policy; static HTML generation and content checks passed.
Corrected the earlier regression report: low yield is not evidence to bypass the verifier. Preserved baseline and generation behavior. Includes the already requested preview clarification showing content and other unknown counts from final scheduling.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added read-only candidate-accounting JSON/HTML and CLI with reconciled exclusive dispositions plus independent deterministic, review and scheduling evidence. Reproduced the 138-card result, documented actual sentence-reservation conflicts, and recorded the approved follow-up order. Verified with 196 tests and full artifact generation; no model inference or selection changes.
<!-- SECTION:FINAL_SUMMARY:END -->
