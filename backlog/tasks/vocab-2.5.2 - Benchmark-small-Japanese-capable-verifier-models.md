---
id: VOCAB-2.5.2
title: Benchmark small Japanese-capable verifier models
status: To Do
assignee:
  - '@codex'
created_date: '2026-09-02 07:29'
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
- [ ] #1 Pinned MLX revisions of Qwen3.5-2B OptiQ, Gemma 2 2B JPN 4-bit, and Qwen3-1.7B 4-bit receive identical prompts, decoding settings, gold records, and acceptance policy
- [ ] #2 Each candidate passes a sequential 20-card guarded smoke test with no known false accepts before any larger run; Phi-4 Mini is evaluated only if the first three fail to provide a viable result
- [ ] #3 Evaluation includes frozen development data, held-out HxH episodes, a second show, and the hard-negative suite from VOCAB-2.5.1
- [ ] #4 The comparison reports false accepts, accepted precision and confidence bounds, acceptance and positive coverage, abstentions, option-order disagreement, invalid-output rate, cards per second, artifact size, and peak unified memory overall and by failure category
- [ ] #5 Only one model runs at a time under the 4 GiB default MLX limit, and any resource-limit breach or incomplete process cleanup fails the candidate
- [ ] #6 The final report recommends adopt, conservative ensemble, or retain the deterministic baseline; insufficient statistical evidence cannot produce an adoption recommendation
- [ ] #7 Any adopted configuration pins the model revision, prompt versions, decoding parameters, vote policy, thresholds, and measured resource envelope as a regression baseline
<!-- AC:END -->
