---
id: VOCAB-2.5
title: Benchmark a constrained small local verifier
status: In Progress
assignee:
  - '@codex'
created_date: '2026-08-27 11:36'
updated_date: '2026-09-02 07:42'
labels: []
dependencies:
  - VOCAB-2.1
references:
  - 'https://github.com/MrLesk/Backlog.md'
documentation:
  - docs/future-app.md
parent_task_id: VOCAB-2
priority: high
type: spike
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Determine whether a 1.5B-4B Japanese-capable local model can replace the slow open-ended Qwen 9B passes for a conservative accepted subset using dictionary-grounded multiple-choice decisions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Sense selection uses only surviving JMdict choices plus an explicit none-or-ambiguous option
- [ ] #2 Option order is shuffled and stable sense identity must agree across repeated prompts
- [ ] #3 Subtitle support is checked independently from Japanese sense selection
- [ ] #4 Held-out episodes and a second show report false accepts, coverage, throughput, and memory against the Qwen 9B baseline
- [ ] #5 A smaller model is adopted only when the configured accepted-card precision target is met
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a fail-closed local-inference safety guard before any further benchmarking: one process across all worktrees, a 4 GiB MLX allocation limit, a 3.5 GiB model-artifact ceiling that blocks the 9B model, and cleanup on every exit. 2. Add deterministic JMdict candidate enumeration and a constrained verifier protocol with stable sense IDs, seeded option shuffles, duplicate sense votes, explicit none/ambiguous, and a separate subtitle-support vote. 3. Keep the benchmark resumable and report accepted precision, false accepts, coverage, throughput, and peak memory from already-safe evidence; do not run the 9B teacher again on this Mac. 4. Adopt the 2B path only if the configured precision floor is met; otherwise preserve the frozen deterministic baseline.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Safety incident: overlapping Qwen3.5 9B MLX processes accumulated over 30 GB of unified memory and crashed the Mac. All inference is paused. Decision: permanently block the 9B artifact under the default local safety policy, enforce one inference process and a 4 GiB MLX limit, and run no model during guard implementation/testing.

Implemented the local-inference safety guard in both MLX reviewer paths: exclusive cross-process flock, default 4 GiB MLX allocation limit, non-overridable 6 GiB hard maximum, 3.5 GiB artifact ceiling that rejects Qwen3.5 9B before model loading, 512 MiB cache cap, explicit cleanup, and CLI coverage. No model was loaded. Verification: 152 tests passed; no inference process remains.

Pre-merge runtime clarification: preserved the immutable hxh-e01-e10-hybrid-qwen9b-200-v1 artifacts and pinned 9B configuration as the historical A/B baseline. Removed 9B as an executable CLI default; local review now requires an explicit model, documentation marks the 2B example as experimental, and the artifact/memory guard continues to block unsafe 9B execution on this Mac. Verification: 152 tests passed.
<!-- SECTION:NOTES:END -->
