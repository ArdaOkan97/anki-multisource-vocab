from __future__ import annotations

import html
from typing import Mapping, Optional, Tuple


_POS_LABELS = {
    "名詞": "Noun",
    "代名詞": "Pronoun",
    "動詞": "Verb",
    "形容詞": "い-Adjective",
    "形状詞": "な-Adjective",
    "副詞": "Adverb",
    "連体詞": "Prenominal",
    "感動詞": "Interjection",
    "表現": "Expression",
}


def learner_pos(part_of_speech: str) -> str:
    return _POS_LABELS.get(part_of_speech, part_of_speech)


def hiragana(reading: str) -> str:
    return "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in reading
    )


def _valid_span(
    sentence: str, target: str, start: Optional[int], end: Optional[int]
) -> bool:
    return (
        start is not None
        and end is not None
        and 0 <= start < end <= len(sentence)
        and sentence[start:end] == target
    )


def learner_target_span(
    row: Mapping[str, object]
) -> Tuple[str, Optional[int], Optional[int]]:
    """Prefer the exact lexical span over attached inflection or grammar."""
    sentence = str(row["japanese"])
    lexical_start = row.get("target_lexical_start")
    lexical_end = row.get("target_lexical_end")
    if (
        isinstance(lexical_start, int)
        and isinstance(lexical_end, int)
        and 0 <= lexical_start < lexical_end <= len(sentence)
    ):
        return sentence[lexical_start:lexical_end], lexical_start, lexical_end
    return (
        str(row.get("target_surface") or row["lemma"]),
        row.get("target_start") if isinstance(row.get("target_start"), int) else None,
        row.get("target_end") if isinstance(row.get("target_end"), int) else None,
    )


def blank_target(
    sentence: str, target: str, start: Optional[int] = None, end: Optional[int] = None
) -> str:
    """Escape a sentence and replace its first target occurrence with a review blank."""
    if _valid_span(sentence, target, start, end):
        return (
            html.escape(sentence[:start])
            + '<span class="target-blank">（　）</span>'
            + html.escape(sentence[end:])
        )
    escaped = html.escape(sentence)
    escaped_target = html.escape(target)
    if not escaped_target or escaped_target not in escaped:
        return escaped
    return escaped.replace(
        escaped_target, '<span class="target-blank">（　）</span>', 1
    )


def highlight_target(
    sentence: str, target: str, start: Optional[int] = None, end: Optional[int] = None
) -> str:
    if _valid_span(sentence, target, start, end):
        return (
            html.escape(sentence[:start])
            + f'<span class="target-answer">{html.escape(target)}</span>'
            + html.escape(sentence[end:])
        )
    escaped = html.escape(sentence)
    escaped_target = html.escape(target)
    if not escaped_target:
        return escaped
    return escaped.replace(
        escaped_target, f'<span class="target-answer">{escaped_target}</span>', 1
    )
