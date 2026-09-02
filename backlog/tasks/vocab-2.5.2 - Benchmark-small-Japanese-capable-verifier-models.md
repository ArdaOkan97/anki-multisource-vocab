---
id: VOCAB-2.5.2
title: Benchmark small Japanese-capable verifier models
status: Done
assignee:
  - '@codex'
created_date: '2026-09-02 07:29'
updated_date: '2026-09-02 08:29'
labels: []
dependencies:
  - VOCAB-2.5.1
parent_task_id: VOCAB-2.5
priority: high
type: spike
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Run a controlled, resource-bounded comparison of small local models for dictionary-grounded sense selection and independent English-subtitle support verification. Compare models as conservative selective filters, document their precision-versus-coverage tradeoff, and adopt a model only when held-out evidence supports the configured production precision target.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Pinned MLX revisions of Qwen3.5-2B OptiQ, Gemma 2 2B JPN 4-bit, and Qwen3-1.7B 4-bit receive identical prompts, decoding settings, gold records, and acceptance policy
- [x] #2 Each candidate passes a sequential 20-card guarded smoke test with no known false accepts before any larger run; Phi-4 Mini is evaluated only if the first three fail to provide a viable result
- [x] #3 Evaluation includes frozen development data, held-out HxH episodes, a second show, and the hard-negative suite from VOCAB-2.5.1
- [x] #4 The comparison reports false accepts, accepted precision and confidence bounds, acceptance and positive coverage, abstentions, option-order disagreement, invalid-output rate, cards per second, artifact size, and peak unified memory overall and by failure category
- [x] #5 Only one model runs at a time under the 4 GiB default MLX limit, and any resource-limit breach or incomplete process cleanup fails the candidate
- [x] #6 The final report recommends adopt, conservative ensemble, or retain the deterministic baseline; insufficient statistical evidence cannot produce an adoption recommendation
- [x] #7 Any adopted configuration pins the model revision, prompt versions, decoding parameters, vote policy, thresholds, and measured resource envelope as a regression baseline
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Freeze exact model revisions, identical decoding/prompt policy, a 20-card smoke cohort, and resource-failure rules.
2. Extend the harness with sequential smoke/benchmark orchestration and complete comparison metrics, without allowing concurrent inference.
3. Download and run one candidate at a time under the 4 GiB default guard; stop each candidate on smoke false accepts or resource/cleanup failure.
4. Evaluate surviving candidates on every frozen split, generate a blinded/comparative report, and make a fail-closed recommendation.
5. Verify tests and artifacts, record measured evidence, and package this task as a separate PR.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Pinned and smoke-tested four models in separate guarded processes with identical prompts/decoding. Qwen3.5 2B: 7 accepted, 2 false accepts, 0.714 precision, 1.798 GiB peak. Gemma 2B JPN: 7 accepted, 3 false accepts, 0.571 precision, 1.723 GiB peak. Qwen3 1.7B: 3 accepted, 1 false accept, 0.667 precision, 15 invalid outputs, 1.218 GiB peak. Phi-4 Mini fallback ran only after all primaries failed: 0 accepted, 20 invalid outputs, 2.528 GiB peak. All cleanup probes passed. No model passed smoke, so the larger development/held-out HxH/second-show/hard-negative stages were correctly recorded as not_run_smoke_gate. Recommendation: retain deterministic baseline.

Final verification: 164 tests passed; comparison invariant check confirmed all four cleanup probes, every peak below 4 GiB, all four full split statuses present, and retain-baseline recommendation; git diff --check passed. The smoke gate intentionally prevented every larger run because no candidate qualified.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Benchmarked three pinned primary MLX candidates and the conditional Phi fallback under a shared fail-closed policy. Every candidate was safe but failed quality/format smoke requirements, so no full run or model adoption occurred and the frozen deterministic baseline remains active. Reproducible config, smoke cohort, category metrics, and comparison evidence are committed; verified with measured runs and 164 tests.
<!-- SECTION:FINAL_SUMMARY:END -->
