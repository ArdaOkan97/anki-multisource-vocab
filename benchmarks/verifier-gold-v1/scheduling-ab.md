# Sentence assignment and teaching-order A/B (VOCAB-2.10)

## Change

The prior greedy scheduler permanently reserved its first chosen sentence. The
new default retains greedy ordering initially, then explores bounded reassignment
when an approved candidate for a deferred meaning needs an occupied sentence.
An earlier meaning can move to another approved occurrence. Replaying the whole
sequence rechecks dependencies, unique sentences, staged unknown limits and the
configured harder-unknown gap using only initially known or previously taught
meanings. No semantic equivalence maps or new model judgments are introduced.

Breadth-first search is limited to 64 evaluated states and three forced assignment
choices. It can traverse intermediate schedules that temporarily lose a target,
but publishes a replacement only if it increases yield and retains every original
target. Otherwise the original sequence is preserved. Reaching a bound is reported,
not interpreted as proof that all candidates are impossible. Python callers may
select the unchanged greedy behavior for comparison or lower the search budget.

The review planner now considers replacement examples for selected words with
contested sentences. Such examples remain unapproved until the existing validators
accept them. Planner eligibility at the current known state does not authorize
using that example earlier; the scheduler must replay and check it again.

## Tests

Regression tests demonstrate:

- one reserved example moved to an alternate: **1 → 2 targets**;
- two-step reassignment with a prerequisite: **2 → 3 targets**;
- recomputed order teaches the prerequisite before using it as known context;
- rejected/unreviewed alternatives cannot enter the deck;
- failed alternatives fall through to the next approved example;
- impossible or budget-limited repairs preserve the original result;
- the first 20 cards still have zero other unknown meanings;
- replacement examples appear in the review queue with explicit provenance.

## Matched saved-evidence HxH E01–E10 replay

Inputs: 7,687 candidates, 1,500 curriculum targets; saved validation has 140 accepted,
208 rejected, 112 abstained, and **7,227 unreviewed** candidates. Both arms receive
the same unchanged candidates, decisions and configuration. Input hashes and compact
results are saved in `scheduling-ab-default.json` and `scheduling-ab-legacy-gap.json`.

| Matched configuration | Greedy | Reassignment | Changed assignments |
| --- | ---: | ---: | ---: |
| Current default: harder-unknown tolerance 2.0 | 113 | 113 | 0 |
| Historical diagnostic: harder-unknown gap check disabled | 138 | 138 | 0 |

The historical replay preserves the 138-card preview's audit-position order exactly.
The difference between 113 and 138 is the gap-check setting, **not a scheduling
regression**. The historical flag is only for matched diagnostics; production
defaults and the frozen 200-card baseline have not been changed. Both configurations
retain the same 0/1/2 staged unknown-count limits.

No accepted replacement moves exist in the cached candidate decisions, so the
repair search evaluates zero trial states for these inputs. This is an honest
no-improvement result, not evidence that the unreviewed alternatives fail. Each
arm takes about a second without inference, downloads or media processing.

| Target | Total candidates | Accepted | Unreviewed | Selected in either arm |
| --- | ---: | ---: | ---: | --- |
| 誰 | 18 | 1 | 17 | No; approved sentence is reserved |
| お前 | 64 | 1 | 63 | Yes |
| 君 | 22 | 1 | 21 | Yes |

The new planner queues nine replacement occurrences among its first 40 planned
reviews under default settings, and sixteen under the historical setting.
It no longer assumes an already-selected word has no reason to validate an alternate.
Increasing real yield requires reviewing those alternatives; this A/B does not
fabricate acceptance to demonstrate an improvement.

## Evidence limits

These cached candidates predate the newer occurrence-context metadata version.
Both arms preserve the same legacy metadata policy. Structural assertions verify
unique sentences/learning units, accepted decisions, exact prior-known-only
unknown counts, and the configured difficulty gap. They do **not** independently
certify Japanese senses, readings, subtitle alignment or audible words.
The report is not a fresh 200-card deck or an audio-validated preview. Integrating
audio validation is the separate next task, VOCAB-2.11.

## Reproduce

```console
.venv/bin/python -m vocabdeck.scheduling_ab --candidates .vocabdeck/audits/hxh-e01-e10-vocab-2.5.4-candidates-full.json --validation .vocabdeck/audits/hxh-e01-e10-vocab-2.5.4-validation-full.json --output .vocabdeck/comparisons/hxh-e01-e10-sentence-reassignment-v1.json --summary-output benchmarks/verifier-gold-v1/scheduling-ab-default.json
```

Add `--soft-harder-unknowns` with different output paths for the historical gap
policy replay. This disables the gap check in **both** arms, never in just the new
scheduler. Full local comparison artifacts retain teaching order and deferred
reason/status accounting; tracked summaries omit subtitle/card bodies.
