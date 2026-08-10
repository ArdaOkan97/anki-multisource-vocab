from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence, Tuple


E5_MODEL_ID = "intfloat/multilingual-e5-small"
E5_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


class TextEmbedder(Protocol):
    model_name: str

    def similarity(self, query: str, passage: str) -> float:
        ...


class MultilingualE5Small:
    model_name = f"{E5_MODEL_ID}@{E5_MODEL_REVISION}"

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        model_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.cache_path = cache_path or Path(
            ".vocabdeck/semantic-embeddings.sqlite3"
        )
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = sqlite3.connect(str(self.cache_path))
        self._cache.execute(
            """CREATE TABLE IF NOT EXISTS embeddings (
                 model TEXT NOT NULL,
                 role TEXT NOT NULL,
                 text_hash TEXT NOT NULL,
                 text TEXT NOT NULL,
                 vector_json TEXT NOT NULL,
                 PRIMARY KEY(model, role, text_hash)
               )"""
        )
        self._cache.commit()
        self._model_factory = model_factory
        self._model = None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self._model_factory is not None:
            self._model = self._model_factory()
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - packaging failure path
            raise RuntimeError(
                "Semantic expression analysis requires sentence-transformers"
            ) from exc
        self._model = SentenceTransformer(
            E5_MODEL_ID, revision=E5_MODEL_REVISION
        )
        return self._model

    @lru_cache(maxsize=100_000)
    def _embedding(self, role: str, text: str) -> Tuple[float, ...]:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cached = self._cache.execute(
            """SELECT vector_json FROM embeddings
               WHERE model = ? AND role = ? AND text_hash = ?""",
            (self.model_name, role, text_hash),
        ).fetchone()
        if cached is not None:
            return tuple(float(value) for value in json.loads(cached[0]))
        vector = self._load_model().encode(
            f"{role}: {text}", normalize_embeddings=True, show_progress_bar=False
        )
        values = tuple(float(value) for value in vector)
        self._cache.execute(
            """INSERT OR REPLACE INTO embeddings
               (model, role, text_hash, text, vector_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                self.model_name, role, text_hash, text,
                json.dumps(values, separators=(",", ":")),
            ),
        )
        self._cache.commit()
        return values

    def similarity(self, query: str, passage: str) -> float:
        query_vector = self._embedding("query", query)
        passage_vector = self._embedding("passage", passage)
        return sum(left * right for left, right in zip(query_vector, passage_vector))


@dataclass(frozen=True)
class ExpressionDecision:
    decision: str
    phrase_score: float
    component_score: float
    margin: float
    opacity: float
    phrase_description: str
    component_description: str
    model: str


class ExpressionSemanticScorer:
    """Conservatively choose a dictionary phrase over its component meanings."""

    def __init__(
        self,
        embedder: Optional[TextEmbedder] = None,
        minimum_phrase_score: float = 0.82,
        minimum_margin: float = 0.04,
        minimum_multi_component_margin: float = 0.02,
        minimum_opacity: float = 0.16,
    ) -> None:
        self.embedder = embedder or MultilingualE5Small()
        self.minimum_phrase_score = minimum_phrase_score
        self.minimum_margin = minimum_margin
        self.minimum_multi_component_margin = minimum_multi_component_margin
        self.minimum_opacity = minimum_opacity

    def decide(
        self,
        english: str,
        phrase_senses: Sequence[str],
        component_glosses: Sequence[str],
        standalone: bool = False,
    ) -> ExpressionDecision:
        phrase_descriptions = [value for value in phrase_senses if value]
        component_values = [value for value in component_glosses if value]
        component_description = "Meaning composed from: " + " | ".join(component_values)
        if not english or not phrase_descriptions or not component_values:
            return ExpressionDecision(
                decision="insufficient_evidence",
                phrase_score=0.0,
                component_score=0.0,
                margin=0.0,
                opacity=0.0,
                phrase_description="; ".join(phrase_descriptions),
                component_description=component_description,
                model=self.embedder.model_name,
            )

        scored_phrases = [
            (self.embedder.similarity(english, description), description)
            for description in phrase_descriptions
        ]
        phrase_score, phrase_description = max(scored_phrases)
        component_score = self.embedder.similarity(english, component_description)
        margin = phrase_score - component_score
        opacity = (
            1.0 - self.embedder.similarity(
                phrase_description, component_description
            )
            if len(component_values) > 1
            else 1.0
        )
        required_margin = (
            self.minimum_multi_component_margin
            if len(component_values) > 1 and standalone
            else self.minimum_margin
        )
        decision = (
            "expression"
            if phrase_score >= self.minimum_phrase_score
            and margin >= required_margin
            and opacity >= self.minimum_opacity
            else "components"
            if component_score > phrase_score
            else "ambiguous"
        )
        return ExpressionDecision(
            decision=decision,
            phrase_score=round(phrase_score, 6),
            component_score=round(component_score, 6),
            margin=round(margin, 6),
            opacity=round(opacity, 6),
            phrase_description=phrase_description,
            component_description=component_description,
            model=self.embedder.model_name,
        )
