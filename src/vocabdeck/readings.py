from __future__ import annotations

import importlib.util
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Optional, Protocol, Sequence


_KANA = re.compile(r"[ァ-ヶー]")


def _katakana(value: str) -> str:
    converted = "".join(
        chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char
        for char in value
    )
    return "".join(char for char in converted if _KANA.fullmatch(char))


class ContextualReader(Protocol):
    name: str

    def reading(self, text: str, start: int, end: int) -> Optional[str]:
        ...


class SudachiContextualReader:
    def __init__(self) -> None:
        from sudachipy import dictionary, tokenizer

        dictionary_name = (
            "full" if importlib.util.find_spec("sudachidict_full") else "core"
        )
        self.name = f"sudachi-{dictionary_name}"
        self._tokenizer = dictionary.Dictionary(dict=dictionary_name).create()
        self._mode = tokenizer.Tokenizer.SplitMode.A

    @lru_cache(maxsize=100_000)
    def _tokens(self, text: str) -> tuple:
        return tuple(
            (
                int(morpheme.begin()), int(morpheme.end()),
                str(morpheme.reading_form()),
            )
            for morpheme in self._tokenizer.tokenize(text, self._mode)
        )

    def reading(self, text: str, start: int, end: int) -> Optional[str]:
        selected = [
            token for token in self._tokens(text)
            if token[0] >= start and token[1] <= end
        ]
        if not selected or selected[0][0] != start or selected[-1][1] != end:
            return None
        if any(selected[index][1] != selected[index + 1][0]
               for index in range(len(selected) - 1)):
            return None
        value = _katakana("".join(token[2] for token in selected))
        return value or None


class OpenJTalkContextualReader:
    name = "openjtalk"

    @staticmethod
    @lru_cache(maxsize=100_000)
    def _nodes(text: str) -> tuple:
        import pyopenjtalk

        return tuple(
            (str(node.get("string") or ""), str(node.get("read") or ""))
            for node in pyopenjtalk.run_frontend(text)
        )

    def reading(self, text: str, start: int, end: int) -> Optional[str]:
        target = text[start:end]
        if not target:
            return None
        # OpenJTalk may normalize numerals and fuse words. Match exact node
        # sequences when possible; otherwise leave this analyzer unresolved
        # instead of guessing a character alignment.
        occurrence = text[:start].count(target)
        matches = []
        nodes = self._nodes(text)
        for node_start in range(len(nodes)):
            surface = ""
            reading = ""
            for node_end in range(node_start, min(len(nodes), node_start + 6)):
                surface += nodes[node_end][0]
                reading += nodes[node_end][1]
                if surface == target:
                    matches.append(_katakana(reading))
                    break
                if len(surface) >= len(target):
                    break
        if occurrence >= len(matches):
            return None
        return matches[occurrence] or None


@dataclass(frozen=True)
class ReadingConsensus:
    status: str
    expected: str
    sudachi: Optional[str]
    openjtalk: Optional[str]
    analyzers: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


class ContextualReadingValidator:
    """Cross-check a UniDic reading with independent contextual analyzers."""

    def __init__(
        self,
        readers: Optional[Sequence[ContextualReader]] = None,
    ) -> None:
        self.readers = tuple(readers) if readers is not None else (
            SudachiContextualReader(), OpenJTalkContextualReader(),
        )

    def validate(
        self, text: str, start: Optional[int], end: Optional[int], expected: str
    ) -> ReadingConsensus:
        normalized_expected = _katakana(expected)
        if start is None or end is None or not normalized_expected:
            return ReadingConsensus(
                "unresolved", normalized_expected, None, None, tuple()
            )
        evidence = {
            reader.name: reader.reading(text, int(start), int(end))
            for reader in self.readers
        }
        resolved = {name: value for name, value in evidence.items() if value}
        support = sum(value == normalized_expected for value in resolved.values())
        alternatives = {}
        for value in resolved.values():
            if value != normalized_expected:
                alternatives[value] = alternatives.get(value, 0) + 1
        # UniDic supplies the expected reading and therefore one implicit vote.
        # A single independent agreement establishes a majority. Override it
        # only when both independent analyzers agree on the same alternative.
        status = "unresolved"
        if any(count >= 2 for count in alternatives.values()):
            status = "disagreement"
        elif support:
            status = "agreement"
        sudachi = next(
            (value for name, value in evidence.items() if name.startswith("sudachi")),
            None,
        )
        return ReadingConsensus(
            status=status,
            expected=normalized_expected,
            sudachi=sudachi,
            openjtalk=evidence.get("openjtalk"),
            analyzers=tuple(resolved),
        )
