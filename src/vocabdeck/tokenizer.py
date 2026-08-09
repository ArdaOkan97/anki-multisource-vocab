from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class LexemeToken:
    surface: str
    lemma: str
    reading: str
    part_of_speech: str

    @property
    def key(self) -> str:
        # Merge grammatical uses that look like the same vocabulary item to the
        # learner. Sense-level splitting belongs to the future dictionary layer.
        identity = "\x1f".join((self.lemma, self.reading))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


_HAS_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞"}


def _feature(feature: object, *names: str, default: str = "") -> str:
    for name in names:
        value = getattr(feature, name, None)
        if value and value != "*":
            return str(value)
    return default


class JapaneseTokenizer:
    def __init__(self) -> None:
        try:
            import fugashi
        except ImportError as exc:  # pragma: no cover - packaging failure path
            raise RuntimeError("Japanese tokenization requires: pip install fugashi unidic-lite") from exc
        self._tagger = fugashi.Tagger()

    def tokenize(self, text: str) -> List[LexemeToken]:
        tokens: List[LexemeToken] = []
        for word in self._tagger(text):
            surface = str(word.surface)
            feature = word.feature
            pos = _feature(feature, "pos1", default=str(feature).split(",", 1)[0])
            if pos not in _CONTENT_POS or not _HAS_JAPANESE.search(surface):
                continue
            # Proper names are excellent source metadata but poor global-core
            # vocabulary candidates, and UniDic may romanize their lemma values.
            if pos == "名詞" and _feature(feature, "pos2") == "固有名詞":
                continue
            lemma = _feature(feature, "orthBase", "lemma", default=surface)
            reading = _feature(feature, "kanaBase", "pronBase", "kana", default=surface)
            tokens.append(LexemeToken(surface, lemma, reading, pos))
        return tokens
