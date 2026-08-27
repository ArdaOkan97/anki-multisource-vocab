# Future companion app

This document records product ideas that should remain separate from the initial
Anki vocabulary pipeline.

## Vocabulary and grammar are separate learning layers

The global known-word dictionary should contain lexical vocabulary, not every
Japanese function token. Meaning-bearing particles and constructions such as
`だけ` should be recognized in sentences but should not automatically become
ordinary vocabulary cards.

The app should maintain two independent progress models:

- **Vocabulary progress:** global lexeme identity, source occurrences, and Anki
  review state.
- **Grammar progress:** constructions encountered, explanations opened, examples
  viewed, and optional mastery state.

For example, `それだけだ。` can be represented as:

- vocabulary: `それ` — “that; it”
- grammar marker: `だけ`
- copula: `だ`
- construction: `N + だけ + だ`
- contextual interpretation: “That is all” or “It is only that”

The explanation for `だけ` should describe its limiting function in this exact
sentence instead of presenting one English word as a universal translation.
Other examples can contrast `だけ`, `だけで`, `だけでは`, and `だけしか`.

## Tap-to-explain interaction

Every sentence should preserve token spans and overlapping construction spans.
Tapping a token or highlighted span should open a contextual explanation with:

1. the complete construction span, not only the tapped character;
2. its role in the current sentence;
3. a natural translation and an optional literal breakdown;
4. inflection or attachment information;
5. a few contrasting examples from the learner's imported sources;
6. links to related grammar constructions;
7. the learner's encounter and familiarity history.

Overlapping interpretations should be supported. A token can participate in a
larger construction without being forced into a single one-to-one English gloss.

## Sentence color coding

Color can make sentence structure easier to scan, but it should identify learning
layers rather than claim that every Japanese segment has a fixed English meaning.

Recommended default presentation:

- ordinary known vocabulary: neutral text;
- current vocabulary target: strong accent and solid underline;
- unknown vocabulary: warm accent and dotted underline;
- grammar construction: cool accent or a subtle background band spanning the
  complete construction;
- inflectional ending or auxiliary: a secondary violet accent shown when the
  sentence is expanded;
- omitted or inferred material: shown only in the explanation, not inserted into
  the original subtitle.

The base sentence should remain visually quiet. Detailed coloring can appear on
tap or through a “sentence breakdown” toggle; coloring every token all the time
would become noisy and encourage learners to decode colors instead of Japanese.

Color must never be the only signal. Underline styles, span brackets, labels, and
accessible contrast themes should communicate the same distinctions for
color-blind users and monochrome displays. Users should be able to disable or
customize the palette.

## Immediate next PR: audio-content gate

Before adding presentation features, make sentence audio a fail-closed part of
card validation. The gate should run only after a card passes the text checks:

1. Extract a wider working window around the subtitle cue.
2. Reject or extend clips whose speech is active at either media boundary.
3. Run local Japanese ASR with timestamps without supplying the expected answer
   as a prompt.
4. Normalize the recognized speech and the target reading to kana/phonemes, then
   align the complete subtitle and require explicit target-reading coverage.
5. Permit only documented pronunciation variants (for example, conversational
   vowel changes); ambiguous matches abstain rather than pass.
6. If the target is missing, expand to nearby silence and retry once. If it is
   still absent, try a different occurrence or omit the word.
7. Cache the transcript, alignment, target-coverage score, chosen media bounds,
   and failure reason per occurrence so subsequent deck builds are reproducible.

The initial regression fixture is `誰だ お前。`: the source cue ends at
440.013 seconds, while the second spoken beat begins around 440.3 seconds, after
the current clip's 200 ms tail. The narrow clip must fail and an expanded clip
containing `お前` must pass.

A second regression fixture is `次は私だ！`. The occurrence is pronounced
`つぎはわたしだ`, so the target `私` must be stored and displayed as `わたし`.
If the candidate initially selects the alternate dictionary reading `わたくし`,
the gate should repair it to `わたし` when audio alignment uniquely and
confidently supports that reading. This fixture checks that the gate resolves the
selected occurrence-specific reading, not merely the presence of the written
target or any reading listed by the dictionary.

Reading repair is allowed only when the audio-supported alternative belongs to
the same written form and compatible dictionary entry/sense. After repair, the
pipeline must recompute the lexeme/learning-unit identity and card fingerprint,
then rerun all reading-dependent validation and deduplication checks. The repair,
original reading, selected reading, evidence score, and model/tool versions must
be stored in the audit metadata. If several readings remain plausible or the
audio evidence is weak, do not guess: try another occurrence or omit the card.

Acceptance criteria:

- no production card is accepted when its target reading is absent or clipped;
- when the audio uniquely supports a compatible alternate dictionary reading,
  the card is repaired, re-fingerprinted, and revalidated before acceptance;
- no production card is accepted when a reading mismatch remains unresolved;
- target presence, sentence alignment, and clean audio boundaries are reported
  as separate criteria;
- uncertain ASR/alignment results fail closed;
- widening cannot cross a configured maximum or silently absorb a long adjacent
  utterance;
- the implementation works locally and does not require a hosted API.

## Current PR: sense-aware learning units

The implementation keeps one canonical global lexeme while allowing genuinely
different meanings to be learned from different source occurrences. A learning
unit is keyed by `lexeme_id + sense_key`, not spelling alone. The stable external
form combines `lexeme_key` with a JMdict entry and sense index. Occurrences map
to one unit; candidate generation, scheduling, review fingerprints, Anki note
identity, and learner state deduplicate the same sense across shows but may
introduce a distinct, source-attested sense later.

The current safe first layer uses exact JMdict senses and requires each selected
occurrence to pass the contextual, recoverability, and contextual-gloss gates.
A later refinement may cluster near-synonymous JMdict senses to avoid trivial
duplicate cards. Grammar constructions such as hearsay or appearance `そうだ`
belong to the grammar layer rather than being created automatically as vocabulary
senses.

Initial regression cases:

- `そう？` → reaction sense: `so?` / learner gloss `really?; is that so?`;
- `そうする` → manner sense: `in that way; to do so`;
- learning either occurrence must not mark the other sense as learned;
- the same reaction sense encountered in another show must remain deduplicated.

These cases are covered by automated database and Anki-state regressions.

## TODO: fast constrained local sense verification

Investigate replacing the expensive open-ended review passes with a small local
model answering constrained, dictionary-grounded questions. This is a
performance project, not permission to weaken the fail-closed acceptance policy.

The first classifier should receive the Japanese sentence, the exact target span,
and the JMdict senses that survive deterministic spelling, reading, expression,
and coarse part-of-speech checks. It answers only one constrained label:

```text
What does <target> mean in this sentence?

<Japanese sentence>

A. <candidate sense 1>
B. <candidate sense 2>
C. <candidate sense 3>
D. None of these / ambiguous
```

Use the actual number of surviving senses rather than inventing distractors. The
final choice must always be `None of these / ambiguous`. A `None` result, invalid
output, low score margin, or disagreement must reject that occurrence so the
generator can try another sentence. Constrained decoding should permit only the
listed labels.

Do not ask this one question to prove every property of a card. Use a cheap
cascade:

1. Deterministic token-boundary, reading, part-of-speech, expression, duplicate,
   curriculum, and dictionary checks reject impossible candidates without an
   LLM.
2. The small model selects the contextual dictionary sense from the Japanese
   sentence. Shuffle the options and ask twice; map labels back to stable sense
   IDs and require the same answer both times.
3. A second constrained question checks the subtitle independently: given the
   chosen sense and English subtitle, answer `expressed`, `not expressed`, or
   `ambiguous`. Only `expressed` passes.
4. The learner-facing gloss must be the selected dictionary sense or a
   deterministic approved rendering of it. Do not let the model freely write a
   definition.
5. During evaluation, send disagreements and borderline cases to the current 9B
   reviewer as a teacher. In self-service production, omit unresolved cards
   instead of requiring that slow fallback.

Calibrate candidate models on the existing reviewed Hunter x Hunter occurrences,
then hold out whole episodes and at least one different series. Optimize for
accepted-card precision and false-accept rate, not overall accuracy: abstaining
often is acceptable, approving a wrong card is not. Report throughput, peak
memory, acceptance coverage, false accepts, and disagreement with the 9B teacher.
Do not choose thresholds until this held-out evaluation exists.

Initial experiments should compare a few compact Japanese-capable models (roughly
1.5B–4B parameters) under the same constrained prompt and quantization. A smaller
model is adopted only if its accepted subset meets the precision target. Cache
results by model revision, prompt version, option order, and card fingerprint so
deck regeneration does not repeat inference.

Acceptance criteria:

- no candidate sense is invented outside the deterministic dictionary choices;
- option-order shuffling produces the same stable sense identity;
- `None`, ambiguity, disagreement, and low margin fail closed;
- subtitle support remains independent from Japanese sense selection;
- held-out episodes and a second show meet the configured false-accept target;
- the fast path materially improves cards reviewed per second on Apple Silicon;
- every decision remains reproducible and auditable without a hosted service.

## Later PR: optional card breakdown colors

Do not change the current 200-card review baseline. The next PR should isolate a
small color-coded prototype so its learning value can be judged independently of
the vocabulary, alignment, and difficulty rules already under review.

Scope the first iteration to the generated HTML preview:

1. Keep the front sentence neutral so grammatical coloring does not provide an
   unintended recall hint.
2. Add a collapsed **Show breakdown** control on the answer side.
3. When expanded, preserve the original sentence and decorate its existing spans:
   - current vocabulary target: strong purple accent and solid underline;
   - known vocabulary: neutral text;
   - unknown vocabulary: amber accent and dotted underline;
   - all grammar-layer tokens share one blue color family;
   - particles such as `だけ`, `は`, and `で`: medium blue;
   - suffixes such as `達（たち）`: lighter blue with a suffix underline;
   - auxiliaries, copulas, and inflectional endings such as `ない`, `たい`,
     `た`, and `だ`: blue-violet;
   - complete grammar constructions: subtle background band across the whole
     construction when selected.
4. Show a compact textual breakdown such as
   `それ · だけ · だ` / `vocabulary · limitation grammar · copula` so color is
   never the only explanation.
5. Define colors through CSS variables with dark and light palettes, sufficient
   contrast, and a no-color mode.
6. Use underline styles, labels, or span brackets as redundant accessible cues.
7. Include representative fixtures for ordinary vocabulary, `それだけだ`, an
   inflected verb, an overlapping construction, and an unknown-context word.
8. Add visual and interaction tests for reveal, breakdown toggle, and keyboard
   navigation without changing card ordering or selection.

Acceptance criteria for that PR:

- the existing front-side recall experience is unchanged;
- breakdown coloring is off by default and does not alter sentence text;
- the target and every annotation retain their exact source spans;
- the preview remains usable with color disabled;
- no Anki note model or template migration is included yet.

After reviewing the HTML prototype, a separate PR can adapt the approved design
to Anki Desktop, AnkiMobile, and AnkiDroid and account for differences in their
CSS and JavaScript support.

## Data model sketch

- `grammar_points`: canonical construction, explanation, level, and references.
- `grammar_occurrences`: sentence, start/end spans, selected interpretation, and
  confidence.
- `grammar_relations`: prerequisites, alternatives, and related constructions.
- `learner_grammar_state`: first seen, explanations opened, examples viewed, and
  optional known/mastered timestamps.
- `sentence_annotations`: vocabulary spans, grammar spans, inflections, and
  contextual notes stored independently from the subtitle text.

Grammar detection should use morphological analysis and a curated construction
catalog first. Contextual scoring or an LLM may help choose among overlapping
analyses, but uncertain interpretations should be labeled or withheld rather than
presented as facts.

## Future sentence selection

Sentence difficulty can eventually combine two independent burdens:

- unknown or harder vocabulary;
- unfamiliar grammar constructions.

These should remain configurable. A vocabulary-first learner may allow unfamiliar
grammar because it is tappable, while a graded mode can prefer sentences whose
grammar has already been introduced.

## Suggested app MVP

1. Read the existing SQLite vocabulary/source data.
2. Render a sentence with preserved vocabulary spans.
3. Add a small curated grammar catalog, beginning with common particles and
   constructions found in the imported corpus.
4. Provide tap-to-explain and a sentence-breakdown toggle.
5. Track vocabulary and grammar progress separately.
6. Add grammar-aware sentence difficulty only after annotation quality has been
   measured on real episodes.
