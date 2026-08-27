---
id: VOCAB-1
title: Finalize and merge the frozen hybrid baseline PR
status: Done
assignee:
  - '@codex'
created_date: '2026-08-27 11:21'
updated_date: '2026-08-27 11:48'
labels: []
dependencies: []
references:
  - 'https://github.com/ArdaOkan97/anki-multisource-vocab/pull/8'
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/README.md
priority: high
type: task
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Finish PR #8 without changing the frozen 200-card output. The PR establishes the reviewed hybrid Qwen 9B baseline and its first-100-card human findings as the comparison point for later work.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 PR #8 contains the pinned generation config and immutable 200-card snapshot
- [x] #2 The five findings from cards 40, 56, 68, 69, and 78 are preserved as structured review data
- [x] #3 The full test suite passes on the final PR head
- [x] #4 The PR is merged without rewriting the frozen expected-card snapshot
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Commit the initialized Backlog.md configuration, board, and task specifications to PR #8.
2. Verify the frozen snapshot, human-review annotations, tests, and clean PR merge state.
3. Push the final branch, merge PR #8 without changing the baseline snapshot, and record objective completion evidence.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initialized Backlog.md 1.50.1 with a pinned project dependency, exported board, 16 task specifications, and AGENTS.md workflow guidance. Verified the frozen expected-card SHA-256 remained unchanged and all 127 tests passed.

PR #8 merged as 817fdcbe7a794b49a01d993b1891f384154cbd64 at 2026-08-27T11:47:29Z. Post-merge verification: expected-card SHA-256 839c88e6e31404cef0a4575f932f192d6509b278c7b9b938da69c58c378492aa and 127 tests passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Merged PR #8 with the pinned hybrid baseline, immutable 200-card snapshot, structured first-100-card review findings, and Backlog.md roadmap. Verified the snapshot hash was unchanged and all 127 tests passed on master.
<!-- SECTION:FINAL_SUMMARY:END -->
