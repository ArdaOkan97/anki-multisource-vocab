from __future__ import annotations

from typing import Any, Mapping, Set, Tuple


_FRAGMENT_MARKERS = ("→", "…", "＜", "《", "≪", "≫", "((", "))")
_COLLOQUIAL_MARKERS = ("ねえ", "ぜ", "ぞ", "やが", "りゃ", "じゃん", "～")


def desired_sentence_words(position: int) -> int:
    """Grow from two content words to eight over the first 35 cards."""
    return min(8, 2 + (position // 5))


def example_score(
    example: Mapping[str, Any], target_id: int, known_ids: Set[int], position: int
) -> Tuple[float, dict]:
    word_ids = set(example["word_ids"])
    other_ids = word_ids - {target_id}
    unknown_other = other_ids - known_ids
    word_count = len(word_ids)
    desired = desired_sentence_words(position)
    japanese = str(example.get("japanese") or "")
    english = str(example.get("english") or "")
    missing_translation = not english
    fragment = any(marker in japanese for marker in _FRAGMENT_MARKERS)
    multi_utterance = sum(japanese.count(mark) for mark in "。？！?!") > 1
    colloquial = any(marker in japanese for marker in _COLLOQUIAL_MARKERS)
    single_word = word_count <= 1
    target_changed = str(example.get("surface") or "") != str(example.get("lemma") or "")

    # Unknown context dominates. Quality problems and excessive colloquialism
    # matter most at the beginning, while desired length rises every five cards.
    score = len(unknown_other) * 10.0
    score += 25.0 if missing_translation else 0.0
    score += 15.0 if fragment else 0.0
    score += 8.0 if multi_utterance else 0.0
    score += max(0.0, 5.0 - (position * 0.15)) if colloquial else 0.0
    score += 3.0 if single_word else 0.0
    score += abs(word_count - desired) * 1.25
    score += 0.75 if target_changed else 0.0
    score += max(0, len(english.split()) - 30) * 0.15
    score += len(japanese) * 0.01
    details = {
        "position": position + 1,
        "desired_content_words": desired,
        "content_words": word_count,
        "known_other_words": len(other_ids & known_ids),
        "unknown_other_words": len(unknown_other),
        "missing_translation": missing_translation,
        "fragment": fragment,
        "multi_utterance": multi_utterance,
        "colloquial": colloquial,
        "target_surface_changed": target_changed,
        "selection_score": round(score, 3),
    }
    return score, details
