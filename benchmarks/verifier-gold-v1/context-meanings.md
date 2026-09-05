# Context-meaning dependency guard (VOCAB-2.9)

The previous context counter used persisted component senses even when the
expression analysis had explicitly abstained. In card 21, `何で そう思う？`,
the database recorded an ambiguous `何で` analysis, but context counted the
previously learned `何` meaning. This was not a new-model or threshold problem.

The new candidate path carries versioned, span-level meaning dependencies:

- Resolved expressions stay atomic; resolved components retain their own senses.
- Ambiguous or insufficient-evidence expressions become explicit unresolved
  dependencies, not learned component meanings or invented definitions.
- Dictionary-backed expressions without an analysis in legacy imports also
  remain unresolved. Dictionary presence alone is not contextual evidence.
- Overlapping uncertainties count as one connected span; nested alternatives
  inside an accepted expression cannot override that expression.
- Unresolved meanings are not teachable and cannot inherit initial mastery.
  The deterministic gate defers such examples, including non-target context.
- Target identity must match the exact contextual span. The selector rechecks
  these new constraints even when given a previously accepted validation result.

Existing frozen artifacts retain their original policy unless explicitly rebuilt
with the new metadata. This is not a complete Japanese sense-disambiguation
system: it preserves uncertainty that the existing algorithms already expose.
No thresholds, model prompts, or baseline files changed.

## Paired comparison

```console
python scripts/compare_context_meanings.py \
  --db .vocabdeck/hxh-contextual-senses-1-148.sqlite3 \
  --selection .vocabdeck/audits/hxh-e01-e10-vocab-2.5.4-selection-full.json \
  --output .vocabdeck/comparisons/hxh-context-meanings-v1.json
```

The database opens with SQLite `mode=ro`. This holds the old teaching order and
prior learning constant, rather than regenerating a deck or rerunning reviewers.
Of 138 selected cards, 24 expose unresolved context and 114 are unchanged.
Card 21 moves from one to two other unknown meanings. These 24 are **uncertain
examples, not 24 proven semantic errors**; a new generation run must try other
occurrences rather than filling the quota with these examples.

Tests cover accepted phrases, compositional alternatives, legacy imports,
overlap, stale accepted decisions, metadata corruption, cache isolation, and
enforced read-only database access. The report is a guardrail A/B, not a model
precision benchmark or a prediction of final deck yield.
