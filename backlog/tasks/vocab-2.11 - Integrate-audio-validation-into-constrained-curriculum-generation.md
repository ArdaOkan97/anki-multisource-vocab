---
id: VOCAB-2.11
title: Integrate audio validation into constrained curriculum generation
status: To Do
assignee: []
created_date: '2026-09-05 06:19'
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
- [ ] #1 Audio failures try another occurrence for the same learning meaning before dropping the target
- [ ] #2 Dictionary-supported reading repairs are revalidated and update all reading-dependent identities and artifacts
- [ ] #3 Tests include missing お前 audio, 私 pronounced わたし rather than わたくし, and backchannel or truncated clips
- [ ] #4 No concurrent heavy models; resource limits and audio verdict provenance are recorded
<!-- AC:END -->
