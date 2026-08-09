from __future__ import annotations

import html


_POS_LABELS = {
    "名詞": "Noun",
    "動詞": "Verb",
    "形容詞": "い-Adjective",
    "形状詞": "な-Adjective",
    "副詞": "Adverb",
    "連体詞": "Prenominal",
    "感動詞": "Interjection",
}


def learner_pos(part_of_speech: str) -> str:
    return _POS_LABELS.get(part_of_speech, part_of_speech)


def hiragana(reading: str) -> str:
    return "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in reading
    )


def blank_target(sentence: str, target: str) -> str:
    """Escape a sentence and replace its first target occurrence with a review blank."""
    escaped = html.escape(sentence)
    escaped_target = html.escape(target)
    if not escaped_target or escaped_target not in escaped:
        return escaped
    return escaped.replace(
        escaped_target, '<span class="target-blank">（　）</span>', 1
    )


def highlight_target(sentence: str, target: str) -> str:
    escaped = html.escape(sentence)
    escaped_target = html.escape(target)
    if not escaped_target:
        return escaped
    return escaped.replace(
        escaped_target, f'<span class="target-answer">{escaped_target}</span>', 1
    )
