from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple


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


@dataclass(frozen=True)
class ExpressionAnalysis:
    surface: str
    start: int
    end: int
    entry_id: int
    sense_index: int
    decision: str
    phrase_score: float
    component_score: float
    margin: float
    opacity: float
    phrase_description: str
    component_description: str
    model: str

    @property
    def details_json(self) -> str:
        return json.dumps(
            {
                "phrase_description": self.phrase_description,
                "component_description": self.component_description,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


@dataclass(frozen=True)
class TokenizationResult:
    tokens: List[LexemeToken]
    expression_analyses: List[ExpressionAnalysis]


_HAS_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_EDGE_PUNCTUATION = " \t\r\n。？！?!…～〜＜＞《》≪≫「」『』（）()"
_CONTENT_POS = {
    "名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞",
}
_TRACKED_POS = _CONTENT_POS | {"接頭辞", "接尾辞"}
_PARTICLE_GLOSSES = {
    "で": "particle marking means, instrument, material, location, or cause",
    "に": "particle marking destination, time, location, purpose, or recipient",
    "の": "particle marking possession, attribution, or nominalization",
    "は": "topic or contrast particle",
    "も": "particle meaning also, too, or even",
    "を": "direct-object or route particle",
    "が": "subject or focus particle",
    "へ": "direction particle meaning toward",
    "と": "quotation, accompaniment, or conditional particle",
    "から": "particle meaning from, since, or because",
    "まで": "particle meaning until, as far as, or even",
    "か": "question or alternative particle",
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
    if lemma == "何" and reading == "ナン":
        following = text[end:].lstrip()
        nani_contexts = ("が", "を", "も", "に", "へ", "から", "まで", "か")
        if (
            not following
            or following[0] in "。？！?!"
            or following.startswith(nani_contexts)
        ):
            return lemma, "ナニ", pos
    return lemma, reading, pos


class JapaneseTokenizer:
    def __init__(self, expression_scorer: Optional[object] = None) -> None:
        try:
            import fugashi
        except ImportError as exc:  # pragma: no cover - packaging failure path
            raise RuntimeError("Japanese tokenization requires: pip install fugashi unidic-lite") from exc
        self._tagger = fugashi.Tagger()
        from .dictionary import JMDictExpressionResolver, JMDictResolver

        self._expressions = JMDictExpressionResolver()
        self._dictionary = JMDictResolver()
        self._expression_scorer = expression_scorer

    def _lexical_identity(
        self, feature: object, surface: str, pos: str
    ) -> Tuple[str, str]:
        """Choose a teachable dictionary identity without losing kana spellings.

        UniDic's orthBase is normally the best learner-facing form (for example,
        する instead of 為る). Some productive potential verbs are exceptional:
        威張れる has orthBase 威張れる but the true lemma 威張る. Fall back to
        UniDic's lemma/lForm only when orthBase has no matching JMdict verb and
        the lemma does.
        """
        lemma = _feature(feature, "orthBase", "lemma", default=surface)
        reading = _feature(
            feature, "kanaBase", "pronBase", "kana", default=surface
        )
        if pos != "動詞":
            return lemma, reading
        dictionary_lemma = _feature(feature, "lemma", default=lemma)
        dictionary_reading = _feature(
            feature, "lForm", default=reading
        )
        if (dictionary_lemma, dictionary_reading) == (lemma, reading):
            return lemma, reading
        if self._dictionary.resolve(lemma, reading, pos) is not None:
            return lemma, reading
        if self._dictionary.resolve(
            dictionary_lemma, dictionary_reading, pos
        ) is not None:
            return dictionary_lemma, dictionary_reading
        return lemma, reading

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
            lemma, reading = self._lexical_identity(feature, surface, pos)
            surface_reading = _feature(
                feature, "kana", "pron", default=reading
            )
            original_reading = reading
            lemma, reading, pos = _contextual_identity(
                text, end, lemma, reading, pos
            )
            if reading != original_reading:
                surface_reading = reading
            words.append(
                {
                    "surface": surface,
                    "lemma": lemma,
                    "reading": reading,
                    "surface_reading": surface_reading,
                    "pos": pos,
                    "pos2": _feature(feature, "pos2"),
                    "start": start,
                    "end": end,
                }
            )
        return words

    @staticmethod
    def _component_token(word: Dict[str, Any]) -> Optional[LexemeToken]:
        surface = str(word["surface"])
        pos = str(word["pos"])
        if pos not in _TRACKED_POS or not _HAS_JAPANESE.search(surface):
            return None
        if pos == "名詞" and word["pos2"] == "固有名詞":
            return None
        return LexemeToken(
            surface,
            str(word["lemma"]),
            str(word["reading"]),
            pos,
            int(word["start"]),
            int(word["end"]),
        )

    def _component_tokens(self, words: List[Dict[str, Any]]) -> Dict[int, LexemeToken]:
        return {
            index: token
            for index, word in enumerate(words)
            if (token := self._component_token(word)) is not None
        }

    def _expression_candidate(
        self,
        text: str,
        words: List[Dict[str, Any]],
        start_index: int,
        end_index: int,
    ) -> Optional[tuple]:
        span = words[start_index:end_index]
        if any(word["pos"] == "補助記号" for word in span):
            return None
        if any(
            span[offset]["end"] != span[offset + 1]["start"]
            for offset in range(len(span) - 1)
        ):
            return None
        if not any(word["pos"] in _CONTENT_POS for word in span):
            return None
        start = int(span[0]["start"])
        end = int(span[-1]["end"])
        surface = text[start:end]
        if not _HAS_JAPANESE.search(surface):
            return None
        if self._is_single_morph_in_isolation(surface):
            return None
        surface_reading = "".join(
            str(word["surface_reading"]) for word in span
        )
        particle_inclusive = any(word["pos"] == "助詞" for word in span)
        match = self._expressions.resolve(
            surface, surface_reading, particle_inclusive=particle_inclusive
        )
        if match is None:
            return None
        token = LexemeToken(
            surface, match.lemma, match.reading, "表現", start, end
        )
        return token, match

    @lru_cache(maxsize=100_000)
    def _is_single_morph_in_isolation(self, surface: str) -> bool:
        words = [
            word for word in self._tagger(surface)
            if _feature(word.feature, "pos1") != "補助記号"
        ]
        return len(words) == 1

    def tokenize(self, text: str) -> List[LexemeToken]:
        words = self._morphs(text)
        return list(self._component_tokens(words).values())

    def tokenize_with_context(self, text: str, english: str) -> TokenizationResult:
        words = self._morphs(text)
        components = self._component_tokens(words)
        if self._expression_scorer is None:
            return TokenizationResult(
                tokens=list(components.values()), expression_analyses=[]
            )
        expressions: Dict[int, Tuple[int, LexemeToken]] = {}
        claimed = set()
        analyses: List[ExpressionAnalysis] = []
        index = 0
        while index < len(words):
            selected = None
            for end_index in range(min(len(words), index + 4), index + 1, -1):
                candidate = self._expression_candidate(
                    text, words, index, end_index
                )
                if candidate is None:
                    continue
                expression_token, match = candidate
                component_glosses = []
                for component_index in range(index, end_index):
                    word = words[component_index]
                    token = components.get(component_index)
                    if token is None:
                        if word["pos"] == "助詞":
                            particle_gloss = _PARTICLE_GLOSSES.get(
                                str(word["lemma"])
                            )
                            if particle_gloss is not None:
                                component_glosses.append(particle_gloss)
                        continue
                    dictionary_match = self._dictionary.resolve(
                        token.lemma, token.reading, token.part_of_speech, english
                    )
                    if dictionary_match is not None:
                        component_glosses.append(dictionary_match.gloss)
                decision = self._expression_scorer.decide(
                    english,
                    match.senses,
                    component_glosses,
                    standalone=text.strip(_EDGE_PUNCTUATION) == expression_token.surface,
                    particle_inclusive=any(
                        words[value]["pos"] == "助詞"
                        for value in range(index, end_index)
                    ),
                )
                selected_sense_index = match.sense_indices[
                    match.senses.index(decision.phrase_description)
                ] if decision.phrase_description in match.senses else 0
                analyses.append(
                    ExpressionAnalysis(
                        surface=expression_token.surface,
                        start=expression_token.start,
                        end=expression_token.end,
                        entry_id=match.entry_id,
                        sense_index=selected_sense_index,
                        decision=decision.decision,
                        phrase_score=decision.phrase_score,
                        component_score=decision.component_score,
                        margin=decision.margin,
                        opacity=decision.opacity,
                        phrase_description=decision.phrase_description,
                        component_description=decision.component_description,
                        model=decision.model,
                    )
                )
                if decision.decision == "expression":
                    selected = (end_index, expression_token)
                    break
            if selected is None:
                index += 1
                continue
            end_index, expression_token = selected
            expressions[index] = (end_index, expression_token)
            claimed.update(range(index, end_index))
            index = end_index

        tokens = []
        for word_index in range(len(words)):
            if word_index in expressions:
                tokens.append(expressions[word_index][1])
            elif word_index not in claimed and word_index in components:
                tokens.append(components[word_index])
        return TokenizationResult(tokens=tokens, expression_analyses=analyses)

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
            pos = _feature(
                feature, "pos1", default=str(feature).split(",", 1)[0]
            )
            lemma, reading = self._lexical_identity(
                feature, word_surface, pos
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
        start = text.find(wanted_surface)
        if start >= 0 and wanted_lemma == wanted_surface:
            return start, start + len(wanted_surface)
        return None
