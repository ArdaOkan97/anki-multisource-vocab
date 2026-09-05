---
id: VOCAB-2.11
title: Integrate audio validation into constrained curriculum generation
status: Done
assignee:
  - '@codex'
created_date: '2026-09-05 06:19'
updated_date: '2026-09-05 23:34'
labels: []
dependencies:
  - VOCAB-2.10
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Connect the existing audio-content gate to the constrained curriculum path before accepting and reserving an example. Existing media previews have audio but that is not evidence of audio validation. Preserve bounded sequential model memory usage.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Audio failures try another occurrence for the same learning meaning before dropping the target
- [x] #2 Dictionary-supported reading repairs are revalidated and update all reading-dependent identities and artifacts
- [x] #3 Tests include missing お前 audio, 私 pronounced わたし rather than わたくし, and backchannel or truncated clips
- [x] #4 No concurrent heavy models; resource limits and audio verdict provenance are recorded
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Integrate fail-closed audio decisions into the constrained curriculum before scheduling/reservations, including resumed accepted candidates; rejected clips retry alternate occurrences. 2. Materialize audio timing/reading repairs, update target-dependent context and identity metadata, invalidate stale semantic evidence and require fresh constrained review before acceptance. Persist repair/candidate state for resume. 3. Isolate semantic and each audio backend in sequential child processes sharing the existing inference lock, with pinned cached models, watchdog memory ceiling and explicit resource provenance. No heavy models remain resident in the parent. 4. Add synthetic missing-word, reading-repair, backchannel/truncation, stale-cache/resume and process-failure tests; run a small saved-evidence or mocked integration A/B without claiming new audio accuracy. Document and create a separate PR; fresh 200-card generation remains the following task.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented opt-in --audio-gate orchestration with pre-reservation audio rejection/retry, materialized reading repairs and fresh semantic revalidation, fingerprinted repair/resume state, and sequential offline bounded child inference phases. Verification: 301 pytest tests pass; CLI help and git diff --check pass. New tests include actual alignment logic over synthetic missing-お前 and わたし transcripts, mocked retry/backchannel/truncation integration, resume invalidation, and real no-model subprocess/lock probes. Mocked A/B keeps one learning unit while replacing bad occurrence 1 with accepted occurrence 2. No new real ASR accuracy, production memory peak, or deck throughput measured; next task must begin with a tiny guarded live pilot. Frozen baseline unchanged. See benchmarks/verifier-gold-v1/audio-curriculum-integration.md.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Connected audio validation to constrained curriculum before scheduling, with alternate occurrence retries and fail-closed reading repair/resume handling. Offline sequential subprocess phases record resource provenance under a maximum 4 GiB monitored RSS budget. Verified by 301 passing tests and documented mocked A/B; fresh 200-card live generation remains VOCAB-2.12.
<!-- SECTION:FINAL_SUMMARY:END -->
