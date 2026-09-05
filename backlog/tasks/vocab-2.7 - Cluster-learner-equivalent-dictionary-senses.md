---
id: VOCAB-2.7
title: Cluster learner-equivalent dictionary senses
status: To Do
assignee: []
created_date: '2026-08-27 11:36'
updated_date: '2026-09-05 12:01'
labels: []
dependencies:
  - VOCAB-2.1
  - VOCAB-2.9
  - VOCAB-2.5.6
documentation:
  - baselines/hxh-e01-e10-hybrid-qwen9b-200-v1/human-review.json
parent_task_id: VOCAB-2
priority: medium
type: enhancement
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Suppress cards whose exact JMdict senses differ but whose learner-facing meaning and usage are effectively duplicates.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Card 40 is suppressed after the earlier 何 with なに reading unless its occurrence teaches a materially different meaning
- [ ] #2 Clustering never merges distinct readings merely because spelling matches
- [ ] #3 The same cluster deduplicates across shows while preserving source occurrence history
- [ ] #4 The A/B report exposes every merged and retained sense pair for review
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Generalized contextual equivalence must be justified by VOCAB-2.5.6 evidence before production clustering. Do not introduce word-specific merge maps or infer global/transitive sense equivalence from one accepted occurrence pair.

Prioritization after the 100-pair embedding pilot: defer automatic cross-sense equivalence clustering and further large-scale equivalence annotation for now. The assistant owns future curation/benchmark work; the user is not expected to label 1,000 pairs. The pilot does not establish that duplicate learner meanings are rare in generated decks. Prefer retaining a possible duplicate over incorrectly merging distinct meanings, and preserve existing exact learning-unit deduplication. Revisit using measured duplicate incidence in a future deck-level review or stronger semantic evidence. This deferral applies only to equivalence clustering, not contextual sense correctness, audio checks, or unknown-context/scheduling guardrails. Task remains To Do; no acceptance criteria completed and no production behavior changed.
<!-- SECTION:NOTES:END -->
