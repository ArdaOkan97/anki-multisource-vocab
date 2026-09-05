# VOCAB-2.11: audio-aware curriculum integration

## Scope

Connect the existing audio-content gate to constrained curriculum generation.
This is an opt-in integration, not a new ASR accuracy result or a model-selection
experiment. Frozen generation settings, semantic thresholds, and the reviewed
200-card baseline remain unchanged. Equivalent dictionary-sense deduplication
remains deferred.

## Small deterministic A/B

`tests/test_audio_curriculum.py::test_mocked_ab_replaces_bad_clip_instead_of_losing_word`
runs the same two-occurrence pool with a fixed semantic acceptance stub:

| Variant | Selected occurrence | Cards | Meaning retained |
| --- | --- | --- | --- |
| Text-only | 1 (fixture: target speech missing) | 1 | Yes |
| Audio-gated | 2 (fixture: accepted audio) | 1 | Yes |

The audio verdicts in this comparison are **mocked**. It demonstrates retry and
reservation behavior, not that a recognizer can identify every missing word.
Separate gate-level tests exercise the real kana alignment logic with synthetic
transcripts: missing お前 is rejected after both windows; a boundary failure can
recover with an expanded window; competing-speech markers are rejected; and
decisive わたし evidence repairs 私 originally labeled わたくし.

## Regression coverage

- Audio failure retries another occurrence before discarding a learning meaning.
- Failed audio never enters semantic review or reserves a sentence.
- A resumed text acceptance is audio-checked too. A repaired reading invalidates
  its old semantic acceptance, updates exact learning-unit/candidate keys and
  target context dependencies, and clears obsolete database IDs.
- Fresh semantic rejection prevents a repaired card from entering the deck.
- Matched resume state restores repairs without repeating model calls. Missing
  state, changed source/media/policy, corrupt records, or mismatched validation
  cannot silently restore the old card.
- Repairs that converge on one exact learning unit do not teach it twice.
- Preview furigana and media extraction consume the materialized card's reading
  and timestamps; no database master-reading rewrite is performed.
- Prompt version 2 reaches both the review dataset and verdict validator.
- A real **no-model** child probe verifies separate PID, completed process exit,
  and shared lock exclusion. Tests reject attempts to raise the isolated-phase
  memory ceiling above 4 GiB.

Run with `.venv/bin/python -m pytest -q`. No heavy model inference is needed for
these regression tests.

## Runtime policy and limitations

Only the new constrained `--audio-gate` path uses this isolated orchestration;
the existing standalone audio-review utility is unchanged. Each audio backend
and each semantic frontier runs in a fresh process with a shared inference lock.
The parent holds no model weights and waits for child exit before starting the
next phase. Semantic frontiers are bounded to 40 candidates. Process startup and
repeated audio-model loading cost throughput; cached gate decisions skip repeat
inference.

Models are pinned to the existing revisions in `audio_validation.py`, offline
cache access is required, and CTC runs on CPU. The child has a maximum 4 GiB RSS
watchdog (50 ms sampling), MLX allocation/cache caps where applicable, the
existing 3.5 GiB model-artifact check, and a 900-second default phase timeout.
These are safeguards, not a total-system memory guarantee; brief RSS overshoot
is possible. Runtime PID, duration, observed peak RSS, limits, process exit, and
model revisions are recorded alongside transcript/semantic evidence. Resource
failure aborts the run; it is not interpreted as a bad card or permission to
accept without audio.

No new Whisper/CTC accuracy, production memory peak, or 200-card throughput was
measured in this task. VOCAB-2.12 should first run a tiny guarded live pilot, then
attempt the episodes 1–10 deck with audio/photos and report the actual accepted
count, rejection reasons, memory/latency, and baseline A/B. Do not fill a quota
with unchecked cards if fewer than 200 pass.
