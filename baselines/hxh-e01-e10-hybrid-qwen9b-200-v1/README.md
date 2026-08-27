# Hunter x Hunter episodes 1–10 baseline v1

This directory freezes the exact hybrid configuration and 200-card output that
was reviewed in August 2026. It is a regression baseline, not a gold dataset.
At the time it was frozen, 100 of the 200 rendered cards had been reviewed by
the user. The findings from that first half are preserved in
[`human-review.json`](human-review.json); the remaining 100 cards have not yet
been reviewed.

The baseline is **not deterministic-only**. Candidate construction, dictionary
resolution, difficulty ranking, and curriculum scheduling are deterministic.
Every accepted occurrence also passed three local language-model review passes:

1. contextual word boundary, part of speech, and sense;
2. recoverability of the target meaning from the English subtitle;
3. support for the learner-facing contextual gloss.

All three passes used the pinned MLX Qwen model and prompt versions recorded in
[`config.json`](config.json). No hosted model or API was used. Audio-content
validation and automatic reading repair were not implemented, so they are
explicitly disabled in the frozen configuration.

[`expected-cards.json`](expected-cards.json) contains the stable identity and
learner-visible fields for all 200 selected cards. Future A/B runs should retain
their complete artifacts outside Git, then compare their accepted output against
this snapshot. A changed card is not automatically a regression: the comparison
must distinguish intentional fixes from losses in coverage, order, reading,
sense, sentence quality, or curriculum comprehensibility.

Known limitations at freeze time include the occurrence `次は私だ！`, whose
displayed reading was `わたくし` although the audio says `わたし`. This remains
in the snapshot intentionally so a future reading-repair experiment can prove
that it fixes the error without silently changing unrelated cards.
