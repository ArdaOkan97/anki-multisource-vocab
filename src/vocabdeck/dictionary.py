from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

from jamdict import Jamdict


DICTIONARY_RESOLVER_VERSION = 2

_ENGLISH_WORD = re.compile(r"[a-z][a-z'-]+")
_STOPWORDS = {
    "the", "a", "an", "to", "of", "and", "or", "be", "is", "are", "was", "were",
    "it", "this", "that", "you", "your", "i", "my", "he", "she", "they", "we",
}
_POS_HINTS = {
    "名詞": ("noun", "numeric"),
    "代名詞": ("pronoun", "noun"),
    "動詞": ("verb",),
    "形容詞": ("adjective",),
    "形状詞": ("adjectival noun", "na-adjective"),
    "副詞": ("adverb",),
    "連体詞": ("pre-noun", "prenominal"),
    "感動詞": ("interjection",),
    "表現": ("expressions", "interjection", "adverb"),
}

# UniDic groups lexical 無い and the negative auxiliary under the same coarse
# adjective identity used by this deck. A learner-facing core gloss needs to
# cover both uses; JMdict's first sense only describes absence.
_CORE_GLOSS_OVERRIDES = {
    ("ない", "形容詞"): ("not; nonexistent; without", 1529520, 3),
    # UniDic normalizes 言う to kana. JMdict also has いう as a rare reading of
    # 結う, so spelling/reading alone otherwise selects "to arrange hair".
    ("いう", "動詞"): ("to say; to utter; to call", 1587040, 0),
}


def _hiragana(value: str) -> str:
    return "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in value
    )


def _katakana(value: str) -> str:
    return "".join(
        chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char for char in value
    )


@lru_cache(maxsize=1)
def _dictionary() -> Jamdict:
    return Jamdict()


def _words(value: str) -> set:
    return {
        word for word in _ENGLISH_WORD.findall(value.lower())
        if word not in _STOPWORDS
    }


def _priority(forms: list) -> float:
    tags = {tag for form in forms for tag in form.pri}
    if "ichi1" in tags:
        return 0.9
    if "spec1" in tags or "news1" in tags:
        return 0.65
    if "ichi2" in tags or "spec2" in tags:
        return 0.4
    if tags:
        return 0.2
    return 0.0


@dataclass(frozen=True)
class DictionaryMatch:
    gloss: str
    entry_id: int
    sense_index: int
    confidence: float


@dataclass(frozen=True)
class ExpressionMatch:
    lemma: str
    reading: str
    entry_id: int
    senses: Tuple[str, ...]
    sense_indices: Tuple[int, ...]


class JMDictExpressionResolver:
    """Find exact JMdict entries spanning multiple tokenizer tokens."""

    def __init__(self) -> None:
        self.dictionary = _dictionary()

    @lru_cache(maxsize=100_000)
    def resolve(
        self,
        surface: str,
        reading: str = "",
        particle_inclusive: bool = False,
    ) -> Optional[ExpressionMatch]:
        result = self.dictionary.lookup(
            surface, lookup_chars=False, lookup_ne=False
        )
        best = None
        for entry in result.entries:
            spellings = [form.text for form in entry.kanji_forms]
            readings = [form.text for form in entry.kana_forms]
            if surface not in spellings and surface not in readings:
                continue
            wanted_reading = _hiragana(reading)
            if wanted_reading and readings and wanted_reading not in readings:
                continue
            entry_pos = " ".join(
                str(pos).lower() for sense in entry.senses for pos in sense.pos
            )
            if (
                "expressions (phrases" not in entry_pos
                and "interjection" not in entry_pos
                and not particle_inclusive
            ):
                continue
            selected_reading = wanted_reading or (
                surface if surface in readings
                else (readings[0] if readings else surface)
            )
            senses = []
            sense_indices = []
            for sense_index, sense in enumerate(entry.senses):
                glosses = [
                    gloss.text for gloss in sense.gloss
                    if gloss.lang in ("", "eng")
                ]
                if glosses:
                    description = "; ".join(glosses[:4])
                    if description not in senses:
                        senses.append(description)
                        sense_indices.append(sense_index)
            score = _priority(entry.kanji_forms + entry.kana_forms)
            score += 0.25 if surface in spellings else 0.0
            match = ExpressionMatch(
                lemma=surface,
                reading=_katakana(selected_reading),
                entry_id=int(entry.idseq),
                senses=tuple(senses),
                sense_indices=tuple(sense_indices),
            )
            if best is None or score > best[0]:
                best = (score, match)
        return best[1] if best else None


class JMDictResolver:
    def __init__(self) -> None:
        self.dictionary = _dictionary()

    @lru_cache(maxsize=100_000)
    def resolve(
        self, lemma: str, reading: str, part_of_speech: str, english_context: str = ""
    ) -> Optional[DictionaryMatch]:
        override = _CORE_GLOSS_OVERRIDES.get((lemma, part_of_speech))
        if override:
            gloss, entry_id, sense_index = override
            return DictionaryMatch(gloss, entry_id, sense_index, 5.0)
        # Only JMdict word entries are used below. Kanjidic character expansion
        # and JMnedict proper-name lookup are both discarded and make corpus-wide
        # enrichment dramatically slower.
        result = self.dictionary.lookup(
            lemma, lookup_chars=False, lookup_ne=False
        )
        wanted_reading = _hiragana(reading)
        context_words = _words(english_context)
        best = None
        for entry in result.entries:
            spellings = [form.text for form in entry.kanji_forms]
            readings = [form.text for form in entry.kana_forms]
            spelling_match = lemma in spellings or lemma in readings
            reading_match = wanted_reading in readings
            if not spelling_match and not reading_match:
                continue
            entry_score = (2.0 if spelling_match else 0.0) + (1.0 if reading_match else 0.0)
            entry_score += _priority(entry.kanji_forms + entry.kana_forms)
            entry_kana_usual = any(
                "usually written using kana" in str(item).lower()
                for candidate_sense in entry.senses for item in candidate_sense.misc
            )
            if entry_kana_usual and lemma in readings:
                entry_score += 0.35
            for sense_index, sense in enumerate(entry.senses):
                glosses = [gloss.text for gloss in sense.gloss if gloss.lang in ("", "eng")]
                if not glosses:
                    continue
                pos_text = " ".join(str(pos).lower() for pos in sense.pos)
                pos_match = any(
                    hint in pos_text for hint in _POS_HINTS.get(part_of_speech, ())
                )
                # UniDic reliably identifies reaction fragments as interjections.
                # Do not let a same-reading noun such as 羽（は） or 兎（う）
                # become its learner definition merely because JMdict contains it.
                if part_of_speech == "感動詞" and not pos_match:
                    continue
                gloss_words = _words(" ".join(glosses))
                overlap_count = len(context_words & gloss_words)
                kana_usual = any(
                    "usually written using kana" in str(item).lower() for item in sense.misc
                )
                score = entry_score + (0.55 if pos_match else 0.0)
                # Subtitle translations frequently cover a whole phrase or two
                # speakers, so lexical overlap is only a tiebreaker. JMdict's
                # earlier senses are the safer default for a general core card.
                score += min(0.08, overlap_count * 0.04)
                score += 0.10 if kana_usual and lemma in readings else 0.0
                score -= sense_index * 0.20
                concise = []
                for gloss in glosses:
                    if gloss not in concise:
                        concise.append(gloss)
                    if len(concise) == 3:
                        break
                match = DictionaryMatch(
                    gloss="; ".join(concise), entry_id=int(entry.idseq),
                    sense_index=sense_index, confidence=round(score, 3),
                )
                if best is None or score > best[0]:
                    best = (score, match)
        return best[1] if best else None
