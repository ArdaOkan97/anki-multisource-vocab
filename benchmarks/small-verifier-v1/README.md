# Small verifier benchmark v1

This benchmark compares conservative local filters; it does not replace the
frozen Qwen 9B generation baseline. All candidates received the same 20 gold
cases, versioned prompts, deterministic decoding, two shuffled sense votes,
separate subtitle-support vote, and fail-closed acceptance rule. Models ran in
separate processes with a 4 GiB MLX limit and a post-run lock cleanup probe.

## Smoke result

| Candidate | Accepted | False accepts | Precision | Positive coverage | Invalid | Cards/s | Peak GiB | Artifact GiB | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Qwen3.5 2B OptiQ | 7 | 2 | 0.714 | 0.50 | 0 | 1.026 | 1.798 | 2.108 | failed |
| Gemma 2 2B JPN | 7 | 3 | 0.571 | 0.40 | 0 | 0.879 | 1.723 | 1.390 | failed |
| Qwen3 1.7B | 3 | 1 | 0.667 | 0.20 | 15 | 1.121 | 1.218 | 0.916 | failed |
| Phi-4 Mini fallback | 0 | 0 | — | 0.00 | 20 | 0.852 | 2.528 | 2.030 | nonviable |

Every process completed its cleanup probe and stayed below the memory limit.
The three primary candidates either produced known false accepts or unusable
coverage, which triggered the Phi fallback. Phi produced additional text after
the option letter on every response; the exact-label parser correctly rejected
those outputs. Gemma's literal tokenizer end marker is normalized, but prose is
never silently accepted.

No candidate passed the smoke gate, so running 185 cases would add cost without
being eligible for adoption. `smoke-comparison.json` explicitly records the
development, held-out HxH, second-show, and hard-negative stages as
`not_run_smoke_gate`. The recommendation is therefore to retain the deterministic
baseline. Even a zero-error result on the current small gold set would remain
insufficient for a 99.5% production-precision claim.

`config.json` pins model revisions and the complete execution policy;
`smoke-dataset.json` freezes the exact cohort; `smoke-comparison.json` contains
the machine-readable aggregate and failure-category results.

The tested model repositories are the MLX Community releases for
[Qwen3.5 2B OptiQ](https://huggingface.co/mlx-community/Qwen3.5-2B-OptiQ-4bit),
[Gemma 2 2B JPN](https://huggingface.co/mlx-community/gemma-2-2b-jpn-it-4bit),
[Qwen3 1.7B](https://huggingface.co/mlx-community/Qwen3-1.7B-4bit), and the
[Phi-4 Mini fallback](https://huggingface.co/mlx-community/Phi-4-mini-instruct-4bit).

## Prompt v2 A/B experiment

Prompt v2 adds explicit bare-label output instructions, conservative ambiguity
handling, larger-expression guidance, and a clean-alignment/contamination rule.
Both prompt versions were rerun on the same current code, pinned revisions,
20-card cohort, deterministic decoding, and sequential 4 GiB resource guard.

The original production label mixes semantic, audio, curriculum, duplicate, and
unknown-word failures. Because the verifier receives text only, the A/B report
also measures semantic precision separately: a semantic positive has the expected
JMdict sense and an English subtitle that expresses that sense.

| Candidate | Prompt | Semantic accepted | Semantic false accepts | Semantic precision | Semantic positive coverage | Invalid | Cards/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3.5 2B OptiQ | v1 | 7 | 1 | 0.857 | 0.429 | 0 | 0.868 |
| Qwen3.5 2B OptiQ | v2 | 7 | 0 | 1.000 | 0.500 | 0 | 0.503 |
| Gemma 2 2B JPN | v1 | 7 | 1 | 0.857 | 0.429 | 0 | 0.719 |
| Gemma 2 2B JPN | v2 | 14 | 2 | 0.857 | 0.857 | 0 | 0.495 |
| Qwen3 1.7B | v1 | 3 | 0 | 1.000 | 0.214 | 13 | 0.947 |
| Qwen3 1.7B | v2 | 9 | 2 | 0.778 | 0.500 | 7 | 0.565 |
| Qwen3.5 4B MLX | v1 | 10 | 0 | 1.000 | 0.714 | 0 | 0.322 |
| Qwen3.5 4B MLX | v2 | 8 | 0 | 1.000 | 0.571 | 0 | 0.193 |
| Phi-4 Mini | v1 | 0 | 0 | — | 0.000 | 18 | 0.719 |
| Phi-4 Mini | v2 | 0 | 0 | — | 0.000 | 18 | 0.484 |

The stronger prompt helped Qwen3.5 on this small semantic slice: it removed the
subtitle-contamination false accept, gained one semantic true accept, and reduced
option-order disagreements from three to two. That is promising but only seven
accepted observations, and throughput fell by about 42%. Prompt v1 therefore
remains the production default; v2 stays opt-in until a larger semantic-gold run
confirms the apparent precision improvement. Full values are recorded in
`prompt-v2-ab.json`.

As a safe quality-ceiling follow-up, the pinned Qwen3.5 4B MLX 4-bit revision
`32f3e8ecf65426fc3306969496342d504bfa13f3` was tested under the same guard.
Prompt v1 was stronger for this model: it accepted ten of fourteen semantic
positives with zero semantic false accepts, compared with eight under v2. Its
2.851 GiB artifact and 2.706 GiB peak remained inside both safety limits, though
it ran at only 0.322 cards/s. This is the best smoke result so far, but ten
accepted cases cannot establish production precision. The next useful test needs
more human-gold semantic hard negatives rather than merely adding unreviewed or
obviously positive cards.
