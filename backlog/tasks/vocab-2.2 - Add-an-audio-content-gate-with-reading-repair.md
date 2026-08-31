---
id: VOCAB-2.2
title: Add an audio-content gate with reading repair
status: Done
assignee:
  - '@codex'
created_date: '2026-08-27 11:29'
updated_date: '2026-08-31 03:46'
labels: []
dependencies:
  - VOCAB-2.1
documentation:
  - docs/future-app.md
parent_task_id: VOCAB-2
priority: high
type: feature
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Validate that authentic source audio contains the target reading, has usable boundaries, and is not dominated by competing speech. Repair a displayed reading when one compatible dictionary alternative is uniquely supported.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Card 56 is rejected, re-cut, or replaced when its clip contains unusable competing speech
- [x] #2 The 誰だ お前 clip expands when the target lies beyond the original cue tail
- [x] #3 次は私だ selects わたし instead of わたくし when audio evidence is decisive
- [x] #4 Ambiguous reading or speaker evidence fails closed and all repairs are audited and revalidated
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add pinned optional local MLX Whisper and hiragana/phoneme CTC backends; Whisper supplies orthographic timestamps, while CTC is the reading authority and can fall back to CPU when MPS is unavailable.
2. Implement deterministic orthographic/kana alignment, contextual surface readings for inflections, target-confidence and boundary checks, one bounded expansion retry, and fail-closed multi-speaker/uncertainty decisions.
3. Resolve compatible dictionary alternatives; repair only a uniquely audio-supported reading, recompute identity fields, invalidate stale review stages, and require contextual re-review before final acceptance.
4. Add cacheable JSON decision artifacts, rejection reasons, performance summaries, an HTML preview, and a CLI stage that runs on occurrence candidates before local semantic review.
5. Cover competing speech, boundary expansion, reading repair, ambiguity, cache reuse, artifact compatibility, and inflected readings with automated and real-media regressions.
6. Run the frozen-selection calibration and full regression suite; document self-service setup, ordering, model revisions, and safe failure behavior.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Research changed the backend choice: MLX Whisper word timestamps are useful for orthographic transcription but output 私 and therefore cannot distinguish わたし from わたくし. The selected hiragana/phoneme CTC model directly emits pronunciation, provides frame evidence, is non-autoregressive, and is reported by its author to run in real time on an M2 Air. Whisper is not used as the reading authority.

Final architecture is hybrid and fail-closed. Pinned MLX Whisper provides orthographic target/timestamp evidence only when Sudachi and OpenJTalk unanimously support the occurrence reading; pinned hiragana CTC remains the pronunciation authority for ambiguous readings and repairs. Dictionary identity and contextual surface pronunciation are separated so inflections such as 待つ→待て align correctly.

Real-media verification: 誰だ お前 expands and passes via orthographic+unanimous evidence; 次は私だ repairs ワタクシ→ワタシ via CTC with 1.0 sentence coverage and 0.8259 minimum target confidence; the card-56 multi-speaker cue is rejected before ASR; 分かってんの and ここで待て both pass after contextual-surface alignment. A 47-card frozen-selection calibration accepted 33, rejected 14, and repaired 1; 26 accepts used the hybrid orthographic path and 7 used CTC. Cached decisions rerun in milliseconds. The uncached MLX sweep is intentionally opt-in and should be applied to the multi-occurrence candidate pool before local semantic review.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented an opt-in, fail-closed hybrid audio gate before semantic review. Pinned MLX Whisper verifies target content and boundaries; pinned hiragana CTC resolves ambiguous pronunciations and repairs compatible dictionary readings while invalidating stale review fingerprints. Decisions, transcripts, alignments, bounds, model revisions, repairs, and rejection reasons are cached and can be previewed in HTML. Verified all four acceptance fixtures on real Hunter x Hunter media, two additional inflection regressions, a 47-card frozen-selection calibration (33 accepted, 14 safely rejected, 1 repaired), and 138 passing automated tests.
<!-- SECTION:FINAL_SUMMARY:END -->
