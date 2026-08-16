from __future__ import annotations

import html
from typing import Mapping, Optional, Sequence, Tuple


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


def learner_target_spans(row: Mapping[str, object]) -> list[Tuple[int, int]]:
    """Return every analyzed occurrence of the target lexeme in the sentence."""
    sentence = str(row["japanese"])
    raw_spans = row.get("target_lexical_spans")
    spans: list[Tuple[int, int]] = []
    if isinstance(raw_spans, Sequence) and not isinstance(raw_spans, (str, bytes)):
        for raw_span in raw_spans:
            if (
                isinstance(raw_span, Sequence)
                and not isinstance(raw_span, (str, bytes))
                and len(raw_span) == 2
                and isinstance(raw_span[0], int)
                and isinstance(raw_span[1], int)
                and 0 <= raw_span[0] < raw_span[1] <= len(sentence)
            ):
                spans.append((raw_span[0], raw_span[1]))
    if not spans:
        _, start, end = learner_target_span(row)
        if start is not None and end is not None:
            spans.append((start, end))
    return sorted(set(spans))


def _render_spans(
    sentence: str, spans: Sequence[Tuple[int, int]], replacement: str
) -> str:
    valid = sorted(set(
        (start, end) for start, end in spans
        if 0 <= start < end <= len(sentence)
    ))
    if not valid:
        return html.escape(sentence)
    parts = []
    cursor = 0
    for start, end in valid:
        if start < cursor:
            continue
        parts.append(html.escape(sentence[cursor:start]))
        if "{target}" in replacement:
            parts.append(replacement.format(target=html.escape(sentence[start:end])))
        else:
            parts.append(replacement)
        cursor = end
    parts.append(html.escape(sentence[cursor:]))
    return "".join(parts)


def blank_target(
    sentence: str, target: str, start: Optional[int] = None, end: Optional[int] = None,
    spans: Optional[Sequence[Tuple[int, int]]] = None,
) -> str:
    """Escape a sentence and blank the analyzed occurrences of its target lexeme."""
    if spans:
        return _render_spans(
            sentence, spans, '<span class="target-blank">（　）</span>'
        )
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
    sentence: str, target: str, start: Optional[int] = None, end: Optional[int] = None,
    spans: Optional[Sequence[Tuple[int, int]]] = None,
) -> str:
    if spans:
        return _render_spans(
            sentence, spans, '<span class="target-answer">{target}</span>'
        )
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
