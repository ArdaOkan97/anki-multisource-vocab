from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping

from wordfreq import zipf_frequency


METRICS = ("source", "general", "hybrid")
_KANJI = re.compile(r"[\u3400-\u9fff]")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


@lru_cache(maxsize=100_000)
def general_zipf(lemma: str) -> float:
    """Estimated occurrences on a base-10 Zipf scale (larger is more common)."""
    return float(zipf_frequency(lemma, "ja"))


def score_components(candidate: Mapping[str, Any]) -> Dict[str, float]:
    lemma = str(candidate["lemma"])
    zipf = general_zipf(lemma)
    source_count = max(1, int(candidate.get("source_count") or 1))
    sentence_words = max(1, int(candidate.get("sentence_word_count") or 1))
    sentence_unknown = max(1, int(candidate.get("sentence_unknown_word_count") or 1))

    # Zipf 6.8 is extremely common; 2.5 and below is specialized/rare.
    general = _clamp((6.8 - zipf) / 4.3)
    source = _clamp(1.0 / math.sqrt(source_count))
    other_words = max(0, sentence_words - 1)
    other_unknown = max(0, sentence_unknown - 1)
    unknown_ratio = other_unknown / other_words if other_words else 0.0
    length_burden = _clamp(max(0, sentence_words - 2) / 10)
    sentence = (unknown_ratio * 0.7) + (length_burden * 0.3)

    characters = [char for char in lemma if char.strip()]
    kanji_count = len(_KANJI.findall(lemma))
    length = _clamp(max(0, len(characters) - 1) / 5)
    kanji_density = kanji_count / len(characters) if characters else 0.0
    form = (length * 0.55) + (kanji_density * 0.45)

    sentence_text = str(candidate.get("japanese") or "")
    missing_translation = 1.0 if not candidate.get("english") else 0.0
    fragment = 1.0 if any(
        mark in sentence_text for mark in ("→", "…", "＜", "《", "≪", "≫")
    ) else 0.0
    colloquial = 1.0 if any(
        mark in sentence_text for mark in ("ねえ", "ぜ", "ぞ", "やが", "りゃ", "じゃん", "～")
    ) else 0.0
    too_short = 1.0 if sentence_words <= 1 else 0.0
    quality = _clamp(
        (missing_translation * 0.40) + (fragment * 0.30)
        + (colloquial * 0.20) + (too_short * 0.10)
    )

    # Interjections and one-kana fillers are frequent in dialogue but rarely
    # belong at the very front of a general-purpose core deck.
    kana_only = bool(re.fullmatch(r"[\u3040-\u30ffー]+", lemma))
    filler = lemma in {"ん", "んな", "うん", "えっ", "あっ", "うっ"}
    noise = 1.0 if candidate.get("part_of_speech") == "感動詞" or filler else 0.0
    if kana_only and len(lemma) == 1:
        noise = max(noise, 0.8)
    return {
        "general_zipf": round(zipf, 3),
        "general": round(general, 6),
        "source": round(source, 6),
        "sentence": round(sentence, 6),
        "form": round(form, 6),
        "quality": round(quality, 6),
        "colloquial": colloquial,
        "noise": noise,
    }


def difficulty_score(candidate: Mapping[str, Any], metric: str) -> tuple:
    if metric not in METRICS:
        raise ValueError(f"Unknown difficulty metric: {metric}")
    parts = score_components(candidate)
    if metric == "source":
        raw = (
            (parts["source"] * 0.80) + (parts["sentence"] * 0.10)
            + (parts["quality"] * 0.10) + (parts["noise"] * 0.20)
        )
    elif metric == "general":
        raw = (
            parts["general"] + (parts["form"] * 0.05)
            + (parts["quality"] * 0.10) + (parts["noise"] * 0.20)
        )
    else:
        raw = (
            (parts["general"] * 0.55)
            + (parts["source"] * 0.15)
            + (parts["sentence"] * 0.20)
            + (parts["form"] * 0.05)
            + (parts["quality"] * 0.05)
            + (parts["noise"] * 0.20)
        )
    return round(_clamp(raw) * 100, 3), parts


def rank_candidates(
    candidates: Iterable[Mapping[str, Any]], metric: str = "hybrid"
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        score, breakdown = difficulty_score(row, metric)
        row["difficulty_metric"] = metric
        row["difficulty_score"] = score
        row["difficulty_breakdown"] = breakdown
        # Preserve the old field name for callers created during the MVP.
        row["rank_score"] = score
        ranked.append(row)
    ranked.sort(
        key=lambda row: (
            row["difficulty_score"],
            -int(row.get("source_count") or 0),
            int(row.get("cue_index") or 0),
            str(row["lexeme_key"]),
        )
    )
    return ranked
