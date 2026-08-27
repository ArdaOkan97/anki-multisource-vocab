---
id: VOCAB-2.1
title: Build baseline A/B comparison reports
status: Done
assignee:
  - '@codex'
created_date: '2026-08-27 11:29'
updated_date: '2026-08-27 12:26'
labels: []
dependencies: []
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/config.json
modified_files:
  - README.md
  - src/vocabdeck/cli.py
  - src/vocabdeck/comparison.py
  - tests/test_comparison.py
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Compare any candidate selection with the frozen 200-card snapshot and produce a reviewable report before changing production defaults.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The report shows retained, removed, added, reordered, and learner-visible changed cards
- [x] #2 The report separately identifies reading, sense, gloss, sentence, translation, audio, and unknown-count changes
- [x] #3 The report checks the five first-half human findings and the curriculum unknown-word invariants
- [x] #4 Machine-readable JSON and a human-readable HTML or Markdown report are produced
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the frozen card schema and existing CLI/report conventions.
2. Implement a reusable baseline-versus-candidate comparator with stable card matching and categorized learner-visible diffs.
3. Add curriculum-invariant and frozen human-finding checks.
4. Emit machine-readable JSON and reviewable HTML.
5. Add focused automated tests and run the relevant suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented `vocabdeck compare-baseline` with card-array/selection loading, learning-unit retention and LCS reorder detection, categorized learner-visible changes, unambiguous same-lexeme sense replacements, curriculum invariant checks, frozen human-finding status checks, and JSON/HTML outputs. Added README usage and focused tests.

Verification: full unittest suite passes (132 tests). Frozen baseline self-comparison reports 200 retained, 0 removed/added/reordered/changed, all change categories at 0, curriculum passed, and all five known findings unchanged as expected.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added a deterministic baseline A/B comparison command that reports retention, removals, additions, true reorderings, same-lexeme sense replacements, and categorized learner-visible changes. It also evaluates staged unknown-context limits and tracks each frozen human finding without claiming changed cases are automatically fixed. Produces JSON and HTML reports. Verified by the complete 132-test suite, six focused baseline/comparison tests, compileall, diff checks, and a 200-card frozen-baseline self-comparison with zero differences and a passing curriculum gate.
<!-- SECTION:FINAL_SUMMARY:END -->
