# Candidate accounting: VOCAB-2.8

This read-only report explains the existing 138-card run. It does not rerun an
LLM, modify the candidate pool or selection, change thresholds, or validate audio.
The frozen reviewed baseline remains untouched.

## Reproduce

```console
vocabdeck explain-curriculum-candidates \
  --input .vocabdeck/audits/hxh-e01-e10-vocab-2.5.4-candidates-full.json \
  --validation .vocabdeck/audits/hxh-e01-e10-vocab-2.5.4-validation-full.json \
  --selection .vocabdeck/audits/hxh-e01-e10-vocab-2.5.4-selection-full.json \
  --harder-unknown-tolerance none \
  --json-output .vocabdeck/audits/hxh-e01-e10-candidate-accounting.json \
  --html-output .vocabdeck/audits/hxh-e01-e10-candidate-accounting.html
```

Use the run's actual harder-unknown tolerance: `none` means difficulty affects
ranking but is not a hard exclusion. Unknown-count limits remain hard and are
read from the selection summary (legacy defaults: 0 through card 20, 1 through
card 200, 2 thereafter). No generation policy is inferred from the file name.

## What the numbers actually mean

The pool has **7,687 target-occurrence pairs**, **2,260 distinct sentences**, and
**1,500 learning meanings**. A sentence can be a candidate for several targets;
these are not 7,687 distinct sentences. This pool was capped at 100 candidates per
target and 1,500 targets; it is not the universe of possible cards.

Only **460** pairs have model-review evidence: **140 accepted**, **208 rejected**,
and **112 abstained**. **7,227 have no model review**. Two accepted pairs were not
scheduled. Model acceptance does not prove correctness, especially for unvalidated
audio or incorrectly identified non-target meanings.

At the final state (next card 139, one other unknown allowed), every candidate
gets exactly one primary category using the precedence documented in the report:

| Primary disposition | Candidates |
| --- | ---: |
| Selected | 138 |
| Alternative to an already selected meaning | 1,888 |
| Deterministic rejection | 894 |
| Deterministic abstention | 29 |
| Recorded validation rejection | 181 |
| Recorded validation abstention | 104 |
| Sentence reserved by another selected card | 29 |
| Too many other unknown meanings | 4,272 |
| Unknown dependency has no difficulty score in the pool | 152 |
| **Total** | **7,687** |

These exclusive categories must not be mixed with model outcome totals: an
alternative to a taught meaning may itself have a model rejection, for example.
Each row retains independent deterministic results, model-review evidence, all
final-state dependency blockers, and the owner of a reserved sentence.
There are no otherwise-eligible unreviewed candidates under this final snapshot;
this does not rule out gains from revising earlier sentence assignments.

## The scheduling concern is real

For **誰**, the pool contains 18 candidates: only one model-reviewed (accepted)
and 17 unreviewed. Its exclusive primary categories are eight deterministic
rejections, three sentence reservations, six unknown-limit blocks and one
unscored dependency.

| 誰 candidate | Review | Why unavailable now |
| --- | --- | --- |
| #2092: 誰だ お前。 | Accepted | Reserved by card 22, お前 |
| #2093: 君 誰？ | Not reviewed | Reserved by card 27, 君 |
| #2095: 次は 誰が行く？ | Not reviewed | Reserved by card 24, 行く |

お前 has 64 candidates (63 distinct sentences), of which one was reviewed;
君 has 22 candidates, of which one was reviewed. Their remaining alternatives
were not all rejected. This is evidence for coordinating scarce sentence
assignments, not permission to assume any unreviewed alternative will pass.

## Limits and next steps

- This is a **final-state snapshot**, not a historical search trace. It cannot
  prove when an unreviewed candidate first became blocked or visited.
- Context identities are used as stored. The known `何で`/`何` issue can undercount
  unknown meanings; zero warnings is not a guarantee of correct teaching order.
- Missing context metadata is reported as unknown count `null`, never zero.
- Old validation artifacts lack full occurrence fingerprints. The command rejects
  duplicate/orphan positions, conflicting available identities, and mismatched
  selected occurrences; it cannot verify absent provenance. Recorded input hashes
  identify files, not prove an old review belongs to every current prompt field.
- Keep the verifier and baseline unchanged while addressing VOCAB-2.9 → 2.7 →
  2.10 → 2.11 → 2.12. Do not adopt the earlier proposed model-bypass risk router
  merely because this run yielded fewer than 200 cards.

## Input SHA-256

| Artifact | SHA-256 |
| --- | --- |
| candidates-full.json | `1a4faa79b00d62aaf2a59f6b9eabc9f059894c7961cb1be5962a0d6cf241ffb3` |
| validation-full.json | `80ea1848c5aae06a6167141cfb16ff46dd9876c57fb51de964d5095038799ed6` |
| selection-full.json | `a9d1210d2303330f3e1997b6e1e2ea624395439eaed52484e33bb2608014dbb7` |
