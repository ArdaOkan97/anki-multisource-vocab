from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class LexemeToken:
    surface: str
    lemma: str
    reading: str
    part_of_speech: str
    start: int = 0
    end: int = 0

    @property
    def key(self) -> str:
        # Merge grammatical uses that look like the same vocabulary item to the
        # learner. Sense-level splitting belongs to the future dictionary layer.
        identity = "\x1f".join((self.lemma, self.reading))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


_HAS_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_CONTENT_POS = {
    "名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞",
}


def _feature(feature: object, *names: str, default: str = "") -> str:
    for name in names:
        value = getattr(feature, name, None)
        if value and value != "*":
            return str(value)
    return default


def _contextual_identity(
    text: str, end: int, lemma: str, reading: str, pos: str
) -> tuple:
    if lemma == "いい" and reading == "イイ" and text[end:].startswith("たい"):
        return "いう", "イウ", "動詞"
    return lemma, reading, pos


class JapaneseTokenizer:
    def __init__(self) -> None:
        try:
            import fugashi
        except ImportError as exc:  # pragma: no cover - packaging failure path
            raise RuntimeError("Japanese tokenization requires: pip install fugashi unidic-lite") from exc
        self._tagger = fugashi.Tagger()
        from .dictionary import JMDictExpressionResolver

        self._expressions = JMDictExpressionResolver()

    def _morphs(self, text: str) -> List[Dict[str, Any]]:
        words = []
        cursor = 0
        for word in self._tagger(text):
            surface = str(word.surface)
            start = text.find(surface, cursor)
            if start < 0:  # Defensive fallback for unexpected tokenizer normalization.
                start = text.find(surface)
            if start < 0:
                start = cursor
            end = start + len(surface)
            cursor = end
            feature = word.feature
            pos = _feature(feature, "pos1", default=str(feature).split(",", 1)[0])
            lemma = _feature(feature, "orthBase", "lemma", default=surface)
            reading = _feature(
                feature, "kanaBase", "pronBase", "kana", default=surface
            )
            lemma, reading, pos = _contextual_identity(
                text, end, lemma, reading, pos
            )
            words.append(
                {
                    "surface": surface,
                    "lemma": lemma,
                    "reading": reading,
                    "pos": pos,
                    "pos2": _feature(feature, "pos2"),
                    "start": start,
                    "end": end,
                }
            )
        return words

    def _expression_tokens(
        self, text: str, words: List[Dict[str, Any]]
    ) -> Tuple[Dict[int, LexemeToken], Set[int]]:
        expressions: Dict[int, LexemeToken] = {}
        claimed: Set[int] = set()
        index = 0
        while index < len(words):
            selected = None
            for end_index in range(min(len(words), index + 4), index + 1, -1):
                span = words[index:end_index]
                if any(word["pos"] == "補助記号" for word in span):
                    continue
                if any(
                    span[offset]["end"] != span[offset + 1]["start"]
                    for offset in range(len(span) - 1)
                ):
                    continue
                if not any(word["pos"] in _CONTENT_POS for word in span):
                    continue
                start = int(span[0]["start"])
                end = int(span[-1]["end"])
                surface = text[start:end]
                if not _HAS_JAPANESE.search(surface):
                    continue
                match = self._expressions.resolve(surface)
                if match is not None:
                    selected = (
                        end_index,
                        LexemeToken(
                            surface, match.lemma, match.reading, "表現", start, end
                        ),
                    )
                    break
            if selected is None:
                index += 1
                continue
            end_index, token = selected
            expressions[index] = token
            claimed.update(range(index, end_index))
            index = end_index
        return expressions, claimed

    def tokenize(self, text: str) -> List[LexemeToken]:
        tokens: List[LexemeToken] = []
        words = self._morphs(text)
        expressions, claimed = self._expression_tokens(text, words)
        for index, word in enumerate(words):
            if index in expressions:
                tokens.append(expressions[index])
                continue
            if index in claimed:
                continue
            surface = str(word["surface"])
            pos = str(word["pos"])
            if pos not in _CONTENT_POS or not _HAS_JAPANESE.search(surface):
                continue
            # Proper names are excellent source metadata but poor global-core
            # vocabulary candidates, and UniDic may romanize their lemma values.
            if pos == "名詞" and word["pos2"] == "固有名詞":
                continue
            tokens.append(
                LexemeToken(
                    surface,
                    str(word["lemma"]),
                    str(word["reading"]),
                    pos,
                    int(word["start"]),
                    int(word["end"]),
                )
            )
        return tokens

    def find_inflected_span(
        self, text: str, lemma: str, reading: str, surface: str
    ) -> Optional[Tuple[int, int]]:
        """Locate a lexeme and include directly attached auxiliary inflection."""
        wanted_lemma = lemma
        wanted_reading = reading
        wanted_surface = surface
        words = []
        cursor = 0
        for word in self._tagger(text):
            word_surface = str(word.surface)
            start = text.find(word_surface, cursor)
            if start < 0:
                start = text.find(word_surface)
            if start < 0:
                start = cursor
            end = start + len(word_surface)
            cursor = end
            feature = word.feature
            lemma = _feature(feature, "orthBase", "lemma", default=word_surface)
            reading = _feature(
                feature, "kanaBase", "pronBase", "kana", default=word_surface
            )
            pos = _feature(
                feature, "pos1", default=str(feature).split(",", 1)[0]
            )
            lemma, reading, pos = _contextual_identity(
                text, end, lemma, reading, pos
            )
            words.append(
                {
                    "surface": word_surface,
                    "lemma": lemma,
                    "reading": reading,
                    "pos": pos,
                    "start": start,
                    "end": end,
                }
            )
        for index, word in enumerate(words):
            if (
                word["lemma"] != wanted_lemma
                or word["reading"] != wanted_reading
                or word["surface"] != wanted_surface
            ):
                continue
            end = int(word["end"])
            for following in words[index + 1:]:
                if following["start"] != end or following["pos"] != "助動詞":
                    break
                end = int(following["end"])
            return int(word["start"]), end
        for token in self.tokenize(text):
            if (
                token.lemma == wanted_lemma
                and token.reading == wanted_reading
                and token.surface == wanted_surface
            ):
                return token.start, token.end
        return None
