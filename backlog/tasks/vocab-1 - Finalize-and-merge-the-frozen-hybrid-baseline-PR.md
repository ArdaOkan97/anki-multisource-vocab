---
id: VOCAB-1
title: Finalize and merge the frozen hybrid baseline PR
status: In Progress
assignee:
  - '@codex'
created_date: '2026-08-27 11:21'
updated_date: '2026-08-27 11:40'
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
- [ ] #1 PR #8 contains the pinned generation config and immutable 200-card snapshot
- [ ] #2 The five findings from cards 40, 56, 68, 69, and 78 are preserved as structured review data
- [ ] #3 The full test suite passes on the final PR head
- [ ] #4 The PR is merged without rewriting the frozen expected-card snapshot
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Commit the initialized Backlog.md configuration, board, and task specifications to PR #8.
2. Verify the frozen snapshot, human-review annotations, tests, and clean PR merge state.
3. Push the final branch, merge PR #8 without changing the baseline snapshot, and record objective completion evidence.
<!-- SECTION:PLAN:END -->
