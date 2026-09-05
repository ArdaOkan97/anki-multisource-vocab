# Dictionary-definition calibration pilot

Experimental slice of VOCAB-2.5.6, requested 2026-09-05. No production threshold,
learning identity, curriculum setting, or frozen baseline is changed.

## Question and limits

Can cosine similarity between two English dictionary definitions identify safe
same-word learner-meaning merges? This is **not** a test of which sense a Japanese
sentence uses, subtitle accuracy, or deck quality as a whole. Different dictionary
senses are not automatically equivalent simply because particular occurrences
were previously assigned the wrong senses.

The user authorized a GPT-5.6 agent to help curate examples. `gpt-5.6-sol` drafted
labels while blind to embedding scores. These are **machine labels, not independent
human gold**. A separate metadata-review pass by the same agent does not make them
independent. No requirement for the user to review 1,000 samples is implied.

## Frozen inputs

- `dictionary-calibration-pool-v1.json`: 1,000 unique unordered definition pairs
  across 788 Japanese words, extracted from JMdict alternatives for the existing
  E01–E10 candidate vocabulary. 1,783 distinct definition strings.
- No invented definitions, cross-word random negatives, or identical-gloss controls
  are included. Each pair has the same surface word/reading, two distinct dictionary
  sense IDs, and the concise glosses returned by the existing resolver (up to three
  gloss items, **not the entire dictionary entry**). Same-spelling homonyms and
  uncommon dictionary alternatives are included; this is an inventory sample, not
  a frequency-weighted sample of actual duplicate cards.
- Deterministic word round-robin sampling limits domination by highly polysemous
  words. Unordered definition duplicates are removed before splitting.
- The 100-pair pilot selects one pair per fresh word, stratified using lexical
  overlap, not embedding scores: 40 no-overlap, 38 some-overlap, 22 high-overlap.
  The pool itself is 834/143/23, so the pilot deliberately overweights difficult
  overlap cases; its precision is not a production-population estimate.
- Word-hash split frozen before annotation: **66 calibration / 34 held-out**.
  Different readings of the same written word cannot cross splits. Previously
  inspected words (何, あれ, 分かる, こっち, どっち, くれる) are excluded from the
  fresh pilot and assigned diagnostic status if present in the pool.
- `dictionary-calibration-pilot-evidence.json`: full English glosses, POS, domain,
  usage notes, and spelling/reading restrictions for the 100 pilot pairs. These
  qualifiers are available to the annotation review, **not to the embedder**.

Dictionary text is from the JMdict/EDICT project, provided locally by Jamdict;
retain the source project's attribution/share-alike terms when redistributing.
See the [EDRDG project](https://www.edrdg.org/) and repository README attribution.
No subtitle dialogue, video, audio, or private media paths are included here.

## Annotation rubric

- **Equivalent:** the whole definitions describe the same learner use despite
  different wording; safe to collapse without sentence context.
- **Distinct:** preserve a different referent, domain-specific sense, grammatical
  function, polarity, direction, argument role, or temporal meaning.
- **Uncertain:** underspecified or partially overlapping; context/evidence is
  needed. Uncertainty is not treated as approval.

Do not decide from a shared English synonym, word spelling, sense-index proximity,
or an embedding score. Do not force class balance. Reasons and model provenance
are retained for every label.

The original English-only draft is preserved in
`dictionary-calibration-pilot-labels.json`. During review, omitted dictionary
qualifiers exposed draft mistakes: 仕事's second “work” sense is tagged **physics**;
差's second “difference” sense is tagged **mathematics**; 自ら separates a noun
from an adverb. The same agent then reviewed **all 100** pairs with the full source
metadata, still without cosine scores. That pass is saved separately as
`dictionary-calibration-pilot-reviewed-labels.json`, not overwritten into the draft.

## Threshold protocol

Use the four previously pinned embedding models and unchanged input conventions.
Embed each complete concise English gloss separately; calculate cosine. No Japanese
word, POS, domain tag, or sentence is embedded in this experiment.

For each model, examine observed score boundaries on the **calibration split only**.
Pick the boundary retaining the most equivalent pairs with zero distinct or
uncertain merges on those draft labels. If none exists, the policy is abstain on
everything, not a silently relaxed threshold. Evaluate that fixed threshold once
on held-out words. Retain a calibration threshold curve, false merges, uncertain
acceptances, coverage, and the accepted-count denominator. Models are compared;
none is selected for production using held-out results.

Wilson lower bounds are included only to illustrate small-denominator uncertainty.
Machine-label errors and this deliberately stratified sample invalidate claims
that those bounds establish production reliability. This pilot cannot certify a
99% or 99.5% safe-merge rate or calibrate contextual sense selection.

## Pilot outcome

The gloss-only draft labeled **5 equivalent / 93 distinct / 2 uncertain**.
The metadata-aware pass labeled **2 equivalent / 98 distinct / 0 uncertain**;
all five changes are retained in the two annotation files. This is a conservative
model rubric, not an independently established truth set. The two remaining
equivalent judgments are わがまま and 助かる, both in calibration.

| Model | Safe experimental threshold | Calibration accepted | Held-out accepted |
| --- | --- | ---: | ---: |
| E5-small | None | 0/66 | 0/34 |
| MPNet-base | None | 0/66 | 0/34 |
| BGE-base | None | 0/66 | 0/34 |
| BGE-large | None | 0/66 | 0/34 |

For every model, a draft-labeled distinct calibration pair scores above both
equivalent calibration pairs. Therefore no nonempty upper cosine threshold
satisfies the predeclared zero-false-merge rule. **Rejecting everything is not a
successful deduplication policy.** Precision is undefined, not 100%.

Moreover, held-out labels contain **zero equivalent pairs**, so this pilot cannot
measure held-out recovery of genuine duplicates. Do not reshuffle the test split
after seeing this or call the result proof that no embedding model can work.
The negative-heavy sample reflects sampling different dictionary senses; it is
not a balanced equivalence benchmark or an estimate of duplicate-card prevalence.

Full results and calibration-only curves are in
`dictionary-calibration-pilot-results.json`. All 1,000 pairs were embedded, but
**only 100 were labeled and used for this exploratory evaluation**. The other 900
are an unlabeled pool, not gold and not automatically accepted/rejected.

### Next experiment, not implemented or authorized for production

Before labeling the remaining 900, add more genuinely equivalent examples with
source evidence, plus matching close-but-distinct examples. Keep natural dictionary
pairs separate from any paraphrases or same-sense gloss variants used as synthetic
controls. Obtain an independent label audit, including the proposed equivalent
pairs, and establish a new word-disjoint holdout with both classes before tuning.
Retain full dictionary qualifiers for review; a separate future A/B can test
embedding those qualifiers instead of the concise gloss alone. Any such input
change needs new calibration, not reuse of current thresholds.

This narrow experiment supports investigating embeddings as a candidate-ranking
signal, not approving global sense merges. Contextual sense repair remains a
separate requirement for the originally reported duplicate cards.

## Safety and reproduction

All four models run as separate sequential **CPU** processes with batch size four,
two compute threads, the shared inference lock, and the existing monitored 4 GiB
RSS ceiling. The ceiling is a watchdog, not an instantaneous OS allocation cap.
Pinned cached snapshots are used offline; no local generative LLM is loaded.

| Model | End-to-end process time | Peak process RSS |
| --- | ---: | ---: |
| E5-small | 14.34 s | 1.118 GiB |
| MPNet-base | 28.27 s | 1.056 GiB |
| BGE-base | 26.82 s | 1.060 GiB |
| BGE-large | 72.85 s | 1.931 GiB |

All processes exited with cleanup completed, matched pool fingerprints, and 1,000
scores. Times include model loading/imports, not cloud-agent annotation time.

```console
.venv/bin/python -m vocabdeck.embedding_calibration build --source .vocabdeck/audits/hxh-e01-e10-vocab-2.5.4-candidates-full.json --output benchmarks/verifier-gold-v1/dictionary-calibration-pool-v1.json
.venv/bin/python -m vocabdeck.embedding_calibration evidence --dataset benchmarks/verifier-gold-v1/dictionary-calibration-pool-v1.json --output benchmarks/verifier-gold-v1/dictionary-calibration-pilot-evidence.json
TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 .venv/bin/python -m vocabdeck.embedding_pair_probe --dataset benchmarks/verifier-gold-v1/dictionary-calibration-pool-v1.json --model mpnet --offline --output .vocabdeck/benchmarks/dictionary-calibration-mpnet-v1.json
```

Repeat only the last command for `e5`, `bge-base`, and `bge-large`, waiting for
process exit between models. The frozen pool can be used without the source corpus;
the build step is only for reproducing extraction from the local candidate artifact.

```console
.venv/bin/python -m vocabdeck.embedding_calibration evaluate --dataset benchmarks/verifier-gold-v1/dictionary-calibration-pool-v1.json --annotations benchmarks/verifier-gold-v1/dictionary-calibration-pilot-reviewed-labels.json --evidence benchmarks/verifier-gold-v1/dictionary-calibration-pilot-evidence.json --reports .vocabdeck/benchmarks/dictionary-calibration-e5-v1.json .vocabdeck/benchmarks/dictionary-calibration-mpnet-v1.json .vocabdeck/benchmarks/dictionary-calibration-bge-base-v1.json .vocabdeck/benchmarks/dictionary-calibration-bge-large-v1.json --output benchmarks/verifier-gold-v1/dictionary-calibration-pilot-results.json
```

Fingerprint checks reject changed annotations/inputs, missing or duplicate scores,
invalid cosines, duplicated pairs, and words leaking across splits. Gold fields
remain null. Production adoption still requires independent annotation and a
deck-level A/B against the immutable baseline.
