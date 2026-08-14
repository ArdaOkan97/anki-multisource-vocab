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

## Planned next PR: optional card breakdown colors

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
