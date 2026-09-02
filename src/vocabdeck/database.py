from __future__ import annotations

import json
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from .dictionary import DICTIONARY_RESOLVER_VERSION
from .subtitles import Cue, align_translation
from .tokenizer import LexemeToken


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    series TEXT NOT NULL,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    title TEXT,
    video_path TEXT,
    japanese_subtitle_path TEXT,
    english_subtitle_path TEXT,
    imported_at TEXT NOT NULL,
    UNIQUE(series, season, episode)
);

CREATE TABLE IF NOT EXISTS sentences (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    cue_index INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    japanese TEXT NOT NULL,
    english TEXT,
    difficulty REAL NOT NULL DEFAULT 0,
    UNIQUE(source_id, cue_index)
);

CREATE TABLE IF NOT EXISTS lexemes (
    id INTEGER PRIMARY KEY,
    lexeme_key TEXT NOT NULL UNIQUE,
    lemma TEXT NOT NULL,
    reading TEXT NOT NULL,
    part_of_speech TEXT NOT NULL,
    corpus_count INTEGER NOT NULL DEFAULT 0,
    gloss TEXT,
    dictionary_entry_id INTEGER,
    dictionary_sense_index INTEGER,
    dictionary_confidence REAL,
    dictionary_status TEXT,
    dictionary_version INTEGER,
    known_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS occurrences (
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    surface TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(lexeme_id, sentence_id, surface)
);

CREATE INDEX IF NOT EXISTS occurrences_sentence
ON occurrences(sentence_id, lexeme_id);

CREATE TABLE IF NOT EXISTS occurrence_senses (
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    surface TEXT NOT NULL,
    part_of_speech TEXT NOT NULL,
    gloss TEXT,
    dictionary_entry_id INTEGER,
    dictionary_sense_index INTEGER,
    dictionary_confidence REAL,
    dictionary_status TEXT NOT NULL,
    dictionary_version INTEGER NOT NULL,
    sense_key TEXT,
    PRIMARY KEY(sentence_id, start_char, end_char, lexeme_id)
);

CREATE INDEX IF NOT EXISTS occurrence_senses_lexeme
ON occurrence_senses(lexeme_id, sentence_id);

CREATE INDEX IF NOT EXISTS sentences_source
ON sentences(source_id, cue_index);

CREATE INDEX IF NOT EXISTS lexemes_dictionary_status
ON lexemes(dictionary_status, known_at);

CREATE TABLE IF NOT EXISTS learned_senses (
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    sense_key TEXT NOT NULL,
    known_at TEXT NOT NULL,
    PRIMARY KEY(lexeme_id, sense_key)
);

CREATE TABLE IF NOT EXISTS expression_analyses (
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    surface TEXT NOT NULL,
    dictionary_entry_id INTEGER NOT NULL,
    dictionary_sense_index INTEGER NOT NULL,
    decision TEXT NOT NULL,
    phrase_score REAL NOT NULL,
    component_score REAL NOT NULL,
    margin REAL NOT NULL,
    opacity REAL NOT NULL,
    model TEXT NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY(sentence_id, start_char, end_char, dictionary_entry_id)
);

CREATE TABLE IF NOT EXISTS source_queue (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    rank_score REAL NOT NULL,
    example_sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    PRIMARY KEY(source_id, lexeme_id)
);

CREATE TABLE IF NOT EXISTS anki_cards (
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    sense_key TEXT NOT NULL DEFAULT 'legacy',
    note_id INTEGER NOT NULL UNIQUE,
    card_id INTEGER,
    introduced_source_id INTEGER REFERENCES sources(id),
    example_sentence_id INTEGER REFERENCES sentences(id) ON DELETE SET NULL,
    last_seen_reps INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL,
    PRIMARY KEY(lexeme_id, sense_key)
);

CREATE TABLE IF NOT EXISTS calibration_batches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    source_ids_json TEXT NOT NULL,
    metric TEXT NOT NULL,
    requested_limit INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calibration_cards (
    batch_id INTEGER NOT NULL REFERENCES calibration_batches(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    card_json TEXT NOT NULL,
    PRIMARY KEY(batch_id, position),
    UNIQUE(batch_id, lexeme_id),
    UNIQUE(batch_id, sentence_id)
);

CREATE TABLE IF NOT EXISTS calibration_reviews (
    batch_id INTEGER NOT NULL REFERENCES calibration_batches(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    criterion_code TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('pass', 'flag', 'uncertain')),
    note TEXT,
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY(batch_id, position, criterion_code),
    FOREIGN KEY(batch_id, position)
      REFERENCES calibration_cards(batch_id, position) ON DELETE CASCADE
);
"""


PLANNING_WINDOW = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sense_key(
    dictionary_entry_id: Optional[int],
    dictionary_sense_index: Optional[int],
    part_of_speech: str,
    gloss: Optional[str],
) -> str:
    """Build a stable identity for one meaning without duplicating a lexeme."""
    if dictionary_entry_id is not None and dictionary_sense_index is not None:
        return f"jmdict:{int(dictionary_entry_id)}:{int(dictionary_sense_index)}"
    fallback = f"{part_of_speech}\0{str(gloss or '').strip().lower()}"
    digest = hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:16]
    return f"local:{digest}"


def learning_unit_key(lexeme_key: str, sense_key: str) -> str:
    return f"{lexeme_key}::{sense_key}"


class VocabularyDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._sentence_learning_unit_cache: Dict[int, set] = {}

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        existing = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(lexemes)")
        }
        additions = {
            "gloss": "TEXT",
            "dictionary_entry_id": "INTEGER",
            "dictionary_sense_index": "INTEGER",
            "dictionary_confidence": "REAL",
            "dictionary_status": "TEXT",
            "dictionary_version": "INTEGER",
        }
        for name, sql_type in additions.items():
            if name not in existing:
                self.connection.execute(f"ALTER TABLE lexemes ADD COLUMN {name} {sql_type}")
        occurrence_columns = {
            row["name"] for row in self.connection.execute(
                "PRAGMA table_info(occurrence_senses)"
            )
        }
        if "sense_key" not in occurrence_columns:
            self.connection.execute(
                "ALTER TABLE occurrence_senses ADD COLUMN sense_key TEXT"
            )
        occurrence_rows = list(self.connection.execute(
            """SELECT sentence_id, start_char, end_char, lexeme_id,
                      dictionary_entry_id, dictionary_sense_index,
                      part_of_speech, gloss
               FROM occurrence_senses WHERE sense_key IS NULL"""
        ))
        for row in occurrence_rows:
            self.connection.execute(
                """UPDATE occurrence_senses SET sense_key = ?
                   WHERE sentence_id = ? AND start_char = ? AND end_char = ?
                     AND lexeme_id = ?""",
                (
                    canonical_sense_key(
                        row["dictionary_entry_id"],
                        row["dictionary_sense_index"],
                        str(row["part_of_speech"]), row["gloss"],
                    ),
                    row["sentence_id"], row["start_char"], row["end_char"],
                    row["lexeme_id"],
                ),
            )
        card_columns = {
            row["name"] for row in self.connection.execute(
                "PRAGMA table_info(anki_cards)"
            )
        }
        if "sense_key" not in card_columns:
            self.connection.execute("DROP INDEX IF EXISTS anki_cards_example_sentence")
            self.connection.execute("ALTER TABLE anki_cards RENAME TO anki_cards_legacy")
            self.connection.execute(
                """CREATE TABLE anki_cards (
                     lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
                     sense_key TEXT NOT NULL,
                     note_id INTEGER NOT NULL UNIQUE,
                     card_id INTEGER,
                     introduced_source_id INTEGER REFERENCES sources(id),
                     example_sentence_id INTEGER REFERENCES sentences(id) ON DELETE SET NULL,
                     last_seen_reps INTEGER NOT NULL DEFAULT 0,
                     synced_at TEXT NOT NULL,
                     PRIMARY KEY(lexeme_id, sense_key)
                   )"""
            )
            legacy_rows = list(self.connection.execute(
                "SELECT * FROM anki_cards_legacy"
            ))
            for row in legacy_rows:
                occurrence = self.connection.execute(
                    """SELECT sense_key FROM occurrence_senses
                       WHERE lexeme_id = ? AND sentence_id = ?
                         AND sense_key IS NOT NULL
                       ORDER BY start_char LIMIT 1""",
                    (row["lexeme_id"], row["example_sentence_id"]),
                ).fetchone()
                if occurrence is not None:
                    sense_key = str(occurrence["sense_key"])
                else:
                    lexeme = self.connection.execute(
                        """SELECT dictionary_entry_id, dictionary_sense_index,
                                  part_of_speech, gloss
                           FROM lexemes WHERE id = ?""",
                        (row["lexeme_id"],),
                    ).fetchone()
                    sense_key = canonical_sense_key(
                        lexeme["dictionary_entry_id"],
                        lexeme["dictionary_sense_index"],
                        str(lexeme["part_of_speech"]), lexeme["gloss"],
                    )
                self.connection.execute(
                    """INSERT INTO anki_cards
                       (lexeme_id, sense_key, note_id, card_id,
                        introduced_source_id, example_sentence_id,
                        last_seen_reps, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["lexeme_id"], sense_key, row["note_id"],
                        row["card_id"], row["introduced_source_id"],
                        row["example_sentence_id"], row["last_seen_reps"],
                        row["synced_at"],
                    ),
                )
            self.connection.execute("DROP TABLE anki_cards_legacy")
            card_columns = {
                row["name"] for row in self.connection.execute(
                    "PRAGMA table_info(anki_cards)"
                )
            }
        if "example_sentence_id" not in card_columns:
            self.connection.execute(
                "ALTER TABLE anki_cards ADD COLUMN example_sentence_id INTEGER"
            )
        self.connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS anki_cards_example_sentence
               ON anki_cards(example_sentence_id)
               WHERE example_sentence_id IS NOT NULL"""
        )
        self.connection.execute(
            """INSERT OR IGNORE INTO learned_senses
               (lexeme_id, sense_key, known_at)
               SELECT a.lexeme_id, a.sense_key, COALESCE(l.known_at, a.synced_at)
               FROM anki_cards a JOIN lexemes l ON l.id = a.lexeme_id
               WHERE a.last_seen_reps > 0 OR l.known_at IS NOT NULL"""
        )
        # Expression senses were already selected by the stricter semantic
        # resolver. Preserve them while allowing ordinary legacy matches to be
        # rechecked by the current dictionary resolver.
        self.connection.execute(
            """UPDATE lexemes SET dictionary_version = ?
               WHERE part_of_speech = '表現' AND dictionary_entry_id IS NOT NULL
                 AND dictionary_version IS NULL""",
            (DICTIONARY_RESOLVER_VERSION,),
        )
        analysis_columns = {
            row["name"] for row in self.connection.execute(
                "PRAGMA table_info(expression_analyses)"
            )
        }
        if "dictionary_sense_index" not in analysis_columns:
            self.connection.execute(
                """ALTER TABLE expression_analyses
                   ADD COLUMN dictionary_sense_index INTEGER NOT NULL DEFAULT 0"""
            )
        if "opacity" not in analysis_columns:
            self.connection.execute(
                """ALTER TABLE expression_analyses
                   ADD COLUMN opacity REAL NOT NULL DEFAULT 0"""
            )
        self.connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.connection:
                yield self.connection
        except Exception:
            self.connection.rollback()
            raise

    def add_source(
        self,
        *,
        series: str,
        season: int,
        episode: int,
        title: Optional[str],
        video_path: Optional[str],
        japanese_subtitle_path: str,
        english_subtitle_path: Optional[str],
    ) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO sources
                   (series, season, episode, title, video_path, japanese_subtitle_path,
                    english_subtitle_path, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(series, season, episode) DO UPDATE SET
                     title=excluded.title,
                     video_path=excluded.video_path,
                     japanese_subtitle_path=excluded.japanese_subtitle_path,
                     english_subtitle_path=excluded.english_subtitle_path
                   RETURNING id""",
                (
                    series,
                    season,
                    episode,
                    title,
                    video_path,
                    japanese_subtitle_path,
                    english_subtitle_path,
                    utc_now(),
                ),
            )
            return int(cursor.fetchone()[0])

    def ingest_cues(
        self,
        source_id: int,
        japanese: Sequence[Cue],
        english: Sequence[Cue],
        tokenizer: object,
    ) -> Dict[str, int]:
        from .dictionary import JMDictResolver

        self._sentence_learning_unit_cache.clear()
        sentence_count = 0
        occurrence_count = 0
        contextual_resolver = JMDictResolver()
        with self.transaction() as connection:
            # Queue rows point at selected example sentences, so remove them before
            # replacing an episode's sentence set.
            connection.execute("DELETE FROM source_queue WHERE source_id = ?", (source_id,))
            # A materialized calibration plan is only stable while its source
            # sentences retain their identities. Reimport invalidates the whole
            # affected batch rather than silently leaving a partial checkpoint.
            connection.execute(
                """DELETE FROM calibration_batches WHERE id IN (
                     SELECT DISTINCT cc.batch_id
                     FROM calibration_cards cc
                     JOIN sentences sx ON sx.id = cc.sentence_id
                     WHERE sx.source_id = ?
                   )""",
                (source_id,),
            )
            connection.execute("DELETE FROM sentences WHERE source_id = ?", (source_id,))
            for cue in japanese:
                translation = align_translation(cue, english)
                cursor = connection.execute(
                    """INSERT INTO sentences
                       (source_id, cue_index, start_ms, end_ms, japanese, english)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (source_id, cue.index, cue.start_ms, cue.end_ms, cue.text, translation),
                )
                sentence_id = int(cursor.lastrowid)
                sentence_count += 1
                counts: Dict[tuple, int] = {}
                token_by_identity: Dict[tuple, LexemeToken] = {}
                accepted_expressions = {}
                if hasattr(tokenizer, "tokenize_with_context"):
                    tokenization = tokenizer.tokenize_with_context(
                        cue.text, translation or ""
                    )
                    tokens = tokenization.tokens
                    for analysis in tokenization.expression_analyses:
                        connection.execute(
                            """INSERT INTO expression_analyses
                               (sentence_id, start_char, end_char, surface,
                                dictionary_entry_id, dictionary_sense_index,
                                decision, phrase_score,
                                component_score, margin, opacity, model, details_json)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                sentence_id, analysis.start, analysis.end,
                                analysis.surface, analysis.entry_id,
                                analysis.sense_index, analysis.decision,
                                analysis.phrase_score,
                                analysis.component_score, analysis.margin,
                                analysis.opacity,
                                analysis.model, analysis.details_json,
                            ),
                        )
                        if analysis.decision == "expression":
                            accepted_expressions[(
                                analysis.start, analysis.end, analysis.surface
                            )] = analysis
                else:
                    tokens = tokenizer.tokenize(cue.text)
                for token in tokens:
                    identity = (token.key, token.surface)
                    counts[identity] = counts.get(identity, 0) + 1
                    token_by_identity[identity] = token
                for identity, count in counts.items():
                    token = token_by_identity[identity]
                    connection.execute(
                        """INSERT INTO lexemes
                           (lexeme_key, lemma, reading, part_of_speech, corpus_count, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(lexeme_key) DO UPDATE SET
                             corpus_count = corpus_count + excluded.corpus_count""",
                        (token.key, token.lemma, token.reading, token.part_of_speech, count, utc_now()),
                    )
                    lexeme_id = int(
                        connection.execute(
                            "SELECT id FROM lexemes WHERE lexeme_key = ?", (token.key,)
                        ).fetchone()[0]
                    )
                    analysis = accepted_expressions.get(
                        (token.start, token.end, token.surface)
                    )
                    if analysis is not None:
                        connection.execute(
                            """UPDATE lexemes SET gloss = ?, dictionary_entry_id = ?,
                                      dictionary_sense_index = ?, dictionary_confidence = ?,
                                      dictionary_status = 'matched', dictionary_version = ?
                               WHERE id = ? AND (
                                 dictionary_confidence IS NULL
                                 OR dictionary_confidence < ?
                               )""",
                            (
                                analysis.phrase_description, analysis.entry_id,
                                analysis.sense_index, analysis.phrase_score,
                                DICTIONARY_RESOLVER_VERSION, lexeme_id,
                                analysis.phrase_score,
                            ),
                        )
                    connection.execute(
                        """INSERT INTO occurrences (lexeme_id, sentence_id, surface, count)
                           VALUES (?, ?, ?, ?)""",
                        (lexeme_id, sentence_id, token.surface, count),
                    )
                    occurrence_count += count
                lexeme_ids = {
                    identity: int(connection.execute(
                        "SELECT id FROM lexemes WHERE lexeme_key = ?", (identity[0],)
                    ).fetchone()[0])
                    for identity in counts
                }
                for token in tokens:
                    identity = (token.key, token.surface)
                    lexeme_id = lexeme_ids[identity]
                    analysis = accepted_expressions.get(
                        (token.start, token.end, token.surface)
                    )
                    if analysis is not None:
                        gloss = analysis.phrase_description
                        entry_id = analysis.entry_id
                        sense_index = analysis.sense_index
                        confidence = analysis.phrase_score
                        status = "matched"
                    else:
                        match = contextual_resolver.resolve(
                            token.lemma, token.reading, token.part_of_speech,
                            translation or "", strict_pos=True,
                            japanese_context=cue.text,
                            target_start=token.start,
                        )
                        gloss = match.gloss if match is not None else None
                        entry_id = match.entry_id if match is not None else None
                        sense_index = (
                            match.sense_index if match is not None else None
                        )
                        confidence = (
                            match.confidence if match is not None else None
                        )
                        status = "matched" if match is not None else "missing"
                    sense_key = canonical_sense_key(
                        entry_id, sense_index, token.part_of_speech, gloss
                    )
                    connection.execute(
                        """INSERT OR REPLACE INTO occurrence_senses
                           (sentence_id, start_char, end_char, lexeme_id, surface,
                            part_of_speech, gloss, dictionary_entry_id,
                            dictionary_sense_index, dictionary_confidence,
                            dictionary_status, dictionary_version, sense_key)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            sentence_id, token.start, token.end, lexeme_id,
                            token.surface, token.part_of_speech, gloss, entry_id,
                            sense_index, confidence, status,
                            DICTIONARY_RESOLVER_VERSION, sense_key,
                        ),
                    )
            connection.execute(
                """UPDATE lexemes
                   SET corpus_count = COALESCE((
                     SELECT SUM(o.count) FROM occurrences o WHERE o.lexeme_id = lexemes.id
                ), 0)"""
            )
            connection.execute(
                """DELETE FROM lexemes
                   WHERE corpus_count = 0 AND known_at IS NULL
                     AND NOT EXISTS (
                       SELECT 1 FROM anki_cards a WHERE a.lexeme_id = lexemes.id
                     )"""
            )
            self._rebuild_queue(connection, source_id)
        return {"sentences": sentence_count, "occurrences": occurrence_count}

    def _rebuild_queue(self, connection: sqlite3.Connection, source_id: int) -> None:
        connection.execute("DELETE FROM source_queue WHERE source_id = ?", (source_id,))
        # Frequent words come first. Shorter sentences win as early examples; later
        # refinements can add JLPT/frequency priors without changing the schema.
        connection.execute(
            """INSERT INTO source_queue
               (source_id, lexeme_id, rank_score, example_sentence_id)
               SELECT ?, o.lexeme_id,
                      (1.0 / SUM(o.count)) + (LENGTH(l.lemma) * 0.01),
                      (
                        SELECT o2.sentence_id
                        FROM occurrences o2
                        JOIN sentences s2 ON s2.id = o2.sentence_id
                        WHERE o2.lexeme_id = o.lexeme_id AND s2.source_id = ?
                        ORDER BY LENGTH(s2.japanese), s2.cue_index
                        LIMIT 1
                      )
               FROM occurrences o
               JOIN sentences s ON s.id = o.sentence_id
               JOIN lexemes l ON l.id = o.lexeme_id
               WHERE s.source_id = ?
               GROUP BY o.lexeme_id""",
            (source_id, source_id, source_id),
        )

    def next_unseen(self, source_id: int, limit: int = 20, metric: str = "hybrid") -> List[dict]:
        return self.next_unseen_for_sources([source_id], limit, metric)

    def sense_targets_for_sources(
        self, source_ids: Sequence[int], limit: int = 200,
        metric: str = "curriculum",
    ) -> List[dict]:
        """Rank unseen meanings while retaining one canonical lexeme record."""
        if not source_ids:
            return []
        markers = ",".join("?" for _ in source_ids)
        rows = list(self.connection.execute(
            f"""SELECT l.id AS lexeme_id, l.lexeme_key, l.lemma, l.reading,
                       l.corpus_count AS global_count,
                       os.sense_key, os.part_of_speech, os.gloss,
                       os.dictionary_entry_id, os.dictionary_sense_index,
                       os.dictionary_confidence, os.dictionary_status,
                       a.note_id, a.card_id, a.last_seen_reps,
                       s.id AS sentence_id, s.japanese, s.english,
                       s.start_ms, s.end_ms, s.source_id, s.cue_index,
                       src.series, src.season, src.episode, src.video_path
                FROM occurrence_senses os
                JOIN lexemes l ON l.id = os.lexeme_id
                JOIN sentences s ON s.id = os.sentence_id
                JOIN sources src ON src.id = s.source_id
                LEFT JOIN learned_senses learned
                  ON learned.lexeme_id = os.lexeme_id
                 AND learned.sense_key = os.sense_key
                LEFT JOIN anki_cards a
                  ON a.lexeme_id = os.lexeme_id
                 AND a.sense_key = os.sense_key
                WHERE s.source_id IN ({markers})
                  AND l.known_at IS NULL
                  AND os.dictionary_status = 'matched'
                  AND os.gloss IS NOT NULL AND os.sense_key IS NOT NULL
                  AND learned.lexeme_id IS NULL
                  AND NOT (
                    os.part_of_speech = '感動詞' AND LENGTH(l.lemma) <= 1
                  )
                  AND os.part_of_speech NOT IN ('接頭辞', '接尾辞')
                ORDER BY l.id, os.sense_key,
                         CASE WHEN s.english IS NULL OR s.english = '' THEN 1 ELSE 0 END,
                         LENGTH(s.japanese), s.cue_index""",
            tuple(source_ids),
        ))
        grouped: Dict[tuple, List[dict]] = {}
        for raw in rows:
            row = dict(raw)
            grouped.setdefault(
                (int(row["lexeme_id"]), str(row["sense_key"])), []
            ).append(row)
        candidates = []
        senses_by_lexeme: Dict[int, List[tuple]] = {}
        for key, occurrences in grouped.items():
            senses_by_lexeme.setdefault(key[0], []).append(key)
            row = dict(occurrences[0])
            row["source_count"] = len(occurrences)
            row["sentence_word_count"] = 1
            row["sentence_unknown_word_count"] = 1
            row["learning_unit_key"] = learning_unit_key(
                str(row["lexeme_key"]), str(row["sense_key"])
            )
            candidates.append(row)
        from .difficulty import rank_candidates

        ranked = rank_candidates(candidates, metric)
        sense_ranks = {}
        for lexeme_id, keys in senses_by_lexeme.items():
            keys.sort(key=lambda key: (
                -len(grouped[key]),
                int(grouped[key][0].get("dictionary_sense_index") or 0),
                key[1],
            ))
            for index, key in enumerate(keys):
                sense_ranks[key] = index
        for row in ranked:
            rank = sense_ranks[(int(row["lexeme_id"]), str(row["sense_key"]))]
            row["sense_rank"] = rank
            penalty = min(15.0, rank * 5.0)
            row["difficulty_score"] = round(
                min(100.0, float(row["difficulty_score"]) + penalty), 3
            )
            row["rank_score"] = row["difficulty_score"]
            row["difficulty_breakdown"]["secondary_sense_penalty"] = penalty
        ranked.sort(key=lambda row: (
            float(row["difficulty_score"]),
            int(row["sense_rank"]),
            -int(row["source_count"]),
            str(row["learning_unit_key"]),
        ))
        return ranked[:limit]

    def next_unseen_for_sources(
        self, source_ids: Sequence[int], limit: int = 20, metric: str = "hybrid",
        *, preserve_target_order: bool = False,
    ) -> List[dict]:
        if not source_ids:
            return []
        markers = ",".join("?" for _ in source_ids)
        rows = list(
            self.connection.execute(
                f"""WITH ranked AS (
                       SELECT o.lexeme_id, SUM(o.count) AS source_count,
                              (1.0 / SUM(o.count)) + (LENGTH(l.lemma) * 0.01) AS rank_score
                       FROM occurrences o
                       JOIN sentences sx ON sx.id = o.sentence_id
                       JOIN lexemes l ON l.id = o.lexeme_id
                       WHERE sx.source_id IN ({markers})
                         AND (l.dictionary_status IS NULL OR (
                           l.dictionary_status = 'matched' AND l.gloss IS NOT NULL
                         ))
                         AND NOT (
                           l.part_of_speech = '感動詞' AND LENGTH(l.lemma) <= 1
                         )
                         AND l.part_of_speech NOT IN ('接頭辞', '接尾辞')
                       GROUP BY o.lexeme_id
                   ), examples AS (
                       SELECT r.lexeme_id, r.source_count, r.rank_score,
                              (SELECT o2.sentence_id
                               FROM occurrences o2
                               JOIN sentences s2 ON s2.id = o2.sentence_id
                               JOIN lexemes lx ON lx.id = o2.lexeme_id
                               WHERE o2.lexeme_id = r.lexeme_id
                                 AND s2.source_id IN ({markers})
                               ORDER BY
                                 CASE WHEN s2.english IS NULL OR s2.english = '' THEN 1 ELSE 0 END,
                                 CASE WHEN s2.japanese LIKE '%→%'
                                           OR s2.japanese LIKE '%…%'
                                           OR s2.japanese LIKE '＜%'
                                           OR s2.japanese LIKE '《%'
                                           OR s2.japanese LIKE '≪%'
                                      THEN 1 ELSE 0 END,
                                 CASE WHEN s2.japanese LIKE '%ねえ%'
                                           OR s2.japanese LIKE '%ぜ%'
                                           OR s2.japanese LIKE '%ぞ%'
                                           OR s2.japanese LIKE '%やが%'
                                           OR s2.japanese LIKE '%りゃ%'
                                           OR s2.japanese LIKE '%じゃん%'
                                           OR s2.japanese LIKE '%～%'
                                      THEN 1 ELSE 0 END,
                                 CASE WHEN (
                                   SELECT COUNT(DISTINCT oq.lexeme_id)
                                   FROM occurrences oq WHERE oq.sentence_id = s2.id
                                 ) BETWEEN 2 AND 6 THEN 0 ELSE 1 END,
                                 (SELECT COUNT(DISTINCT ou.lexeme_id)
                                  FROM occurrences ou
                                  JOIN lexemes lu ON lu.id = ou.lexeme_id
                                  WHERE ou.sentence_id = s2.id
                                    AND ou.lexeme_id != o2.lexeme_id
                                    AND lu.known_at IS NULL),
                                 CASE WHEN o2.surface = lx.lemma THEN 0 ELSE 1 END,
                                 ABS(LENGTH(s2.japanese) - 14),
                                 s2.cue_index
                               LIMIT 1) AS sentence_id
                       FROM ranked r
                   )
                   SELECT l.id AS lexeme_id, l.lexeme_key, l.lemma, l.reading, l.gloss,
                          l.dictionary_entry_id, l.dictionary_sense_index,
                          l.dictionary_confidence, l.dictionary_status,
                          l.part_of_speech, q.rank_score, s.japanese, s.english,
                          s.start_ms, s.end_ms, s.source_id, src.series, src.season,
                          src.episode, src.video_path, a.note_id, a.card_id,
                          a.last_seen_reps, q.source_count, l.corpus_count AS global_count,
                          s.cue_index,
                          (SELECT COUNT(DISTINCT os.lexeme_id)
                           FROM occurrences os WHERE os.sentence_id = s.id) AS sentence_word_count,
                          (SELECT COUNT(DISTINCT os.lexeme_id)
                           FROM occurrences os
                           JOIN lexemes ls ON ls.id = os.lexeme_id
                           WHERE os.sentence_id = s.id AND ls.known_at IS NULL
                          ) AS sentence_unknown_word_count
                   FROM examples q
                   JOIN lexemes l ON l.id = q.lexeme_id
                   JOIN sentences s ON s.id = q.sentence_id
                   JOIN sources src ON src.id = s.source_id
                   LEFT JOIN anki_cards a ON a.lexeme_id = l.id
                   WHERE l.known_at IS NULL
                   ORDER BY q.rank_score, s.cue_index""",
                (*source_ids, *source_ids),
            )
        )
        from .difficulty import rank_candidates

        ranked = rank_candidates(rows, metric)
        lexical_difficulties = {
            int(row["lexeme_id"]): float(row["difficulty_score"])
            for row in ranked
        }
        # Load enough candidates to fill the requested batch, but compare only a
        # bounded rolling window at each position. This preserves progressive
        # local choice without making a 5,000-card calibration plan quadratic in
        # the entire corpus.
        pool_size = min(len(ranked), max(100, limit * 5))
        return self._plan_progressive_batch(
            ranked[:pool_size], source_ids, limit, lexical_difficulties,
            preserve_target_order=preserve_target_order,
        )

    def next_unseen_sense_cards_for_sources(
        self, source_ids: Sequence[int], limit: int = 20,
        metric: str = "curriculum",
    ) -> List[dict]:
        """Return one example for each unseen sense-aware learning unit.

        Real dictionary-backed material is identified by ``lexeme + sense``.
        A legacy lexeme queue remains available for imports that have no usable
        dictionary senses, so existing databases and custom tokenizers keep
        working without pretending that a missing sense is a real meaning.
        """
        target_limit = max(100, int(limit) * 5)
        targets = self.sense_targets_for_sources(
            source_ids, target_limit, metric
        )
        cards = self.occurrence_candidates_for_targets(
            targets, source_ids, candidates_per_target=1
        )
        if cards:
            return cards[:limit]
        return self.next_unseen_for_sources(source_ids, limit, metric)

    def _plan_progressive_batch(
        self,
        rows: List[dict],
        source_ids: Sequence[int],
        limit: int,
        lexical_difficulties: Dict[int, float],
        *,
        preserve_target_order: bool = False,
    ) -> List[dict]:
        from .progression import example_score, joint_planning_score
        from .tokenizer import JapaneseTokenizer

        if not rows:
            return rows
        initial_known_ids = {
            int(row[0]) for row in self.connection.execute(
                "SELECT id FROM lexemes WHERE known_at IS NOT NULL"
            )
        }
        known_ids = set(initial_known_ids)
        markers = ",".join("?" for _ in source_ids)
        tokenizer = JapaneseTokenizer()
        examples_by_lexeme: Dict[int, List[dict]] = {}
        reserved_sentence_owners = {
            int(row["example_sentence_id"]): int(row["lexeme_id"])
            for row in self.connection.execute(
                """SELECT lexeme_id, example_sentence_id FROM anki_cards
                   WHERE example_sentence_id IS NOT NULL"""
            )
        }
        used_sentence_ids = set(reserved_sentence_owners)

        def load_examples(row: dict) -> List[dict]:
            lexeme_id = int(row["lexeme_id"])
            if lexeme_id in examples_by_lexeme:
                return examples_by_lexeme[lexeme_id]
            example_rows = list(
                self.connection.execute(
                    f"""SELECT s.id AS sentence_id, s.japanese, s.english,
                               s.start_ms, s.end_ms, s.source_id, s.cue_index,
                               src.series, src.season, src.episode, src.video_path,
                               target_occurrence.surface,
                               target.start_char AS occurrence_start,
                               target.end_char AS occurrence_end,
                               target.part_of_speech AS contextual_part_of_speech,
                               target.gloss AS contextual_gloss,
                               target.dictionary_entry_id AS contextual_dictionary_entry_id,
                               target.dictionary_sense_index AS contextual_dictionary_sense_index,
                               target.dictionary_confidence AS contextual_dictionary_confidence,
                               target.dictionary_status AS contextual_dictionary_status,
                               GROUP_CONCAT(DISTINCT all_words.lexeme_id) AS word_ids_csv
                        FROM occurrences target_occurrence
                        LEFT JOIN occurrence_senses target
                          ON target.lexeme_id = target_occurrence.lexeme_id
                         AND target.sentence_id = target_occurrence.sentence_id
                         AND target.surface = target_occurrence.surface
                        JOIN sentences s ON s.id = target_occurrence.sentence_id
                        JOIN sources src ON src.id = s.source_id
                        JOIN occurrences all_words ON all_words.sentence_id = s.id
                        WHERE target_occurrence.lexeme_id = ?
                          AND s.source_id IN ({markers})
                        GROUP BY s.id, target.start_char, target.end_char,
                                 target_occurrence.lexeme_id,
                                 target_occurrence.surface""",
                    (lexeme_id, *source_ids),
                )
            )
            examples = []
            for candidate_row in example_rows:
                candidate = dict(candidate_row)
                candidate["word_ids"] = {
                    int(value) for value in candidate.pop("word_ids_csv").split(",")
                }
                candidate["lemma"] = row["lemma"]
                lexical_surface = str(candidate["surface"])
                occurrence_start = candidate.pop("occurrence_start")
                occurrence_end = candidate.pop("occurrence_end")
                if occurrence_start is not None and occurrence_end is not None:
                    candidate["target_lexical_start"] = int(occurrence_start)
                    candidate["target_lexical_end"] = int(occurrence_end)
                candidate["target_lexical_spans"] = self.sentence_lexeme_spans(
                    int(candidate["sentence_id"]), lexeme_id
                )
                span = tokenizer.find_inflected_span(
                    candidate["japanese"], row["lemma"], row["reading"],
                    lexical_surface,
                )
                if span:
                    candidate["target_start"], candidate["target_end"] = span
                    candidate.setdefault("target_lexical_start", span[0])
                    candidate.setdefault(
                        "target_lexical_end", span[0] + len(lexical_surface)
                    )
                    candidate["surface"] = candidate["japanese"][span[0]:span[1]]
                examples.append(candidate)
            examples_by_lexeme[lexeme_id] = examples
            return examples

        remaining = list(rows)
        selected = []
        for position in range(min(limit, len(remaining))):
            best_plan = None
            window_end = min(len(remaining), PLANNING_WINDOW)
            scan_ranges = [(0, 1)] if preserve_target_order else [(0, window_end)]
            if not preserve_target_order and window_end < len(remaining):
                scan_ranges.append((window_end, len(remaining)))
            for scan_start, scan_end in scan_ranges:
                for rank_index in range(scan_start, scan_end):
                    row = remaining[rank_index]
                    best_example = None
                    for candidate in load_examples(row):
                        sentence_id = int(candidate["sentence_id"])
                        owner = reserved_sentence_owners.get(sentence_id)
                        if (
                            sentence_id in used_sentence_ids
                            and owner != int(row["lexeme_id"])
                        ):
                            continue
                        score, details = example_score(
                            candidate,
                            int(row["lexeme_id"]),
                            known_ids,
                            position,
                            lexical_difficulties,
                            float(row["difficulty_score"]),
                        )
                        if best_example is None or score < best_example[0]:
                            best_example = (score, candidate, details)
                    if best_example is None:
                        continue
                    example_value, candidate, details = best_example
                    joint_value, planner = joint_planning_score(
                        float(row["difficulty_score"]), example_value, position
                    )
                    plan = (
                        joint_value, float(row["difficulty_score"]), rank_index,
                        row, candidate, details, planner,
                    )
                    if best_plan is None or plan[:3] < best_plan[:3]:
                        best_plan = plan
                # The ordinary path evaluates only the bounded window. Expand
                # across the rest of the corpus solely when every nearby word
                # has lost all usable examples to sentence reservations.
                if best_plan is not None:
                    break
            if best_plan is None:
                break
            _, _, rank_index, row, candidate, details, planner = best_plan
            remaining.pop(rank_index)
            for field in (
                "sentence_id", "japanese", "english", "start_ms", "end_ms", "source_id",
                "cue_index", "series", "season", "episode", "video_path",
            ):
                row[field] = candidate[field]
            row["sentence_word_count"] = len(candidate["word_ids"])
            row["sentence_unknown_word_count"] = details["unknown_other_words"] + 1
            row["target_surface"] = candidate["surface"]
            row["target_start"] = candidate.get("target_start")
            row["target_end"] = candidate.get("target_end")
            row["target_lexical_start"] = candidate.get("target_lexical_start")
            row["target_lexical_end"] = candidate.get("target_lexical_end")
            row["target_lexical_spans"] = candidate.get("target_lexical_spans")
            row["global_part_of_speech"] = row["part_of_speech"]
            for field in (
                "contextual_part_of_speech", "contextual_gloss",
                "contextual_dictionary_entry_id",
                "contextual_dictionary_sense_index",
                "contextual_dictionary_confidence",
                "contextual_dictionary_status",
            ):
                row[field] = candidate.get(field)
            if (
                row.get("contextual_dictionary_status") == "matched"
                and row.get("contextual_part_of_speech") == row["part_of_speech"]
            ):
                row["gloss"] = row.get("contextual_gloss")
                row["dictionary_entry_id"] = row.get(
                    "contextual_dictionary_entry_id"
                )
                row["dictionary_sense_index"] = row.get(
                    "contextual_dictionary_sense_index"
                )
                row["dictionary_confidence"] = row.get(
                    "contextual_dictionary_confidence"
                )
            row["example_progression"] = details
            row["batch_planning"] = planner
            selected.append(row)
            known_ids.add(int(row["lexeme_id"]))
            used_sentence_ids.add(int(candidate["sentence_id"]))
        return selected

    def create_calibration_batch(
        self,
        name: str,
        source_ids: Sequence[int],
        limit: int,
        metric: str = "hybrid",
        *,
        replace: bool = False,
    ) -> Dict[str, Any]:
        """Materialize a stable, resumable plan without changing known state."""
        existing = self.connection.execute(
            "SELECT id FROM calibration_batches WHERE name = ?", (name,)
        ).fetchone()
        if existing is not None and not replace:
            raise ValueError(
                f"Calibration batch already exists: {name}. Use --replace to rebuild it."
            )
        rows = self.next_unseen_for_sources(source_ids, limit, metric)
        with self.transaction() as connection:
            if existing is not None:
                connection.execute(
                    "DELETE FROM calibration_batches WHERE id = ?", (int(existing["id"]),)
                )
            cursor = connection.execute(
                """INSERT INTO calibration_batches
                   (name, source_ids_json, metric, requested_limit, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    name,
                    json.dumps(list(map(int, source_ids)), separators=(",", ":")),
                    metric,
                    int(limit),
                    utc_now(),
                ),
            )
            batch_id = int(cursor.lastrowid)
            for position, row in enumerate(rows, start=1):
                connection.execute(
                    """INSERT INTO calibration_cards
                       (batch_id, position, lexeme_id, sentence_id, card_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        batch_id,
                        position,
                        int(row["lexeme_id"]),
                        int(row["sentence_id"]),
                        json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
        return {
            "name": name,
            "cards": len(rows),
            "requested_limit": int(limit),
            "metric": metric,
            "complete": len(rows) == int(limit),
        }

    def calibration_batch(self, name: str) -> Dict[str, Any]:
        batch = self.connection.execute(
            "SELECT * FROM calibration_batches WHERE name = ?", (name,)
        ).fetchone()
        if batch is None:
            raise KeyError(f"Unknown calibration batch: {name}")
        cards = [
            json.loads(row["card_json"])
            for row in self.connection.execute(
                """SELECT card_json FROM calibration_cards
                   WHERE batch_id = ? ORDER BY position""",
                (int(batch["id"]),),
            )
        ]
        return {
            "id": int(batch["id"]),
            "name": str(batch["name"]),
            "source_ids": json.loads(batch["source_ids_json"]),
            "metric": str(batch["metric"]),
            "requested_limit": int(batch["requested_limit"]),
            "created_at": str(batch["created_at"]),
            "cards": cards,
        }

    def record_calibration_review(
        self,
        name: str,
        position: int,
        criterion_code: str,
        verdict: str,
        note: Optional[str] = None,
    ) -> None:
        from .audit import AUDIT_CRITERION_CODES

        if verdict not in {"pass", "flag", "uncertain"}:
            raise ValueError(f"Unsupported review verdict: {verdict}")
        if criterion_code not in AUDIT_CRITERION_CODES:
            raise ValueError(f"Unsupported audit criterion: {criterion_code}")
        batch = self.connection.execute(
            "SELECT id FROM calibration_batches WHERE name = ?", (name,)
        ).fetchone()
        if batch is None:
            raise KeyError(f"Unknown calibration batch: {name}")
        batch_id = int(batch["id"])
        card = self.connection.execute(
            """SELECT 1 FROM calibration_cards
               WHERE batch_id = ? AND position = ?""",
            (batch_id, int(position)),
        ).fetchone()
        if card is None:
            raise KeyError(f"Position {position} is not in calibration batch {name}")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO calibration_reviews
                   (batch_id, position, criterion_code, verdict, note, reviewed_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(batch_id, position, criterion_code) DO UPDATE SET
                     verdict=excluded.verdict,
                     note=excluded.note,
                     reviewed_at=excluded.reviewed_at""",
                (
                    batch_id,
                    int(position),
                    criterion_code,
                    verdict,
                    note,
                    utc_now(),
                ),
            )

    def calibration_reviews(self, name: str) -> List[dict]:
        batch = self.connection.execute(
            "SELECT id FROM calibration_batches WHERE name = ?", (name,)
        ).fetchone()
        if batch is None:
            raise KeyError(f"Unknown calibration batch: {name}")
        return [
            dict(row) for row in self.connection.execute(
                """SELECT position, criterion_code, verdict, note, reviewed_at
                   FROM calibration_reviews WHERE batch_id = ?
                   ORDER BY position, criterion_code""",
                (int(batch["id"]),),
            )
        ]

    def enrich_dictionary(
        self, source_ids: Optional[Sequence[int]] = None, force: bool = False
    ) -> Dict[str, int]:
        from .dictionary import JMDictResolver

        where = "1 = 1" if force else (
            "(l.dictionary_status IS NULL OR "
            "COALESCE(l.dictionary_version, 0) < ?)"
        )
        parameters: tuple = () if force else (DICTIONARY_RESOLVER_VERSION,)
        if source_ids is not None:
            if not source_ids:
                return {
                    "matched": 0, "missing": 0,
                    "occurrence_matched": 0, "occurrence_missing": 0,
                }
            markers = ",".join("?" for _ in source_ids)
            where += (
                " AND EXISTS (SELECT 1 FROM occurrences ox "
                "JOIN sentences sx ON sx.id = ox.sentence_id "
                f"WHERE ox.lexeme_id = l.id AND sx.source_id IN ({markers}))"
            )
            parameters = (*parameters, *source_ids)
        rows = list(
            self.connection.execute(
                f"""SELECT l.id, l.lemma, l.reading, l.part_of_speech,
                           COALESCE((SELECT GROUP_CONCAT(context.english, ' ')
                                     FROM (SELECT DISTINCT s.english AS english
                                           FROM occurrences o
                                           JOIN sentences s ON s.id = o.sentence_id
                                           WHERE o.lexeme_id = l.id AND s.english IS NOT NULL
                                           LIMIT 5) context), '') AS english_context
                    FROM lexemes l WHERE {where} ORDER BY l.id""",
                parameters,
            )
        )
        resolver = JMDictResolver()
        matched = 0
        missing = 0
        with self.transaction() as connection:
            for row in rows:
                match = resolver.resolve(
                    row["lemma"], row["reading"], row["part_of_speech"], row["english_context"]
                )
                if match is None:
                    connection.execute(
                        """UPDATE lexemes SET gloss = NULL, dictionary_entry_id = NULL,
                                  dictionary_sense_index = NULL, dictionary_confidence = NULL,
                                  dictionary_status = 'missing', dictionary_version = ?
                           WHERE id = ?""",
                        (DICTIONARY_RESOLVER_VERSION, row["id"]),
                    )
                    missing += 1
                else:
                    connection.execute(
                        """UPDATE lexemes SET gloss = ?, dictionary_entry_id = ?,
                                  dictionary_sense_index = ?, dictionary_confidence = ?,
                                  dictionary_status = 'matched', dictionary_version = ?
                           WHERE id = ?""",
                        (
                            match.gloss, match.entry_id, match.sense_index,
                            match.confidence, DICTIONARY_RESOLVER_VERSION, row["id"],
                        ),
                    )
                    matched += 1
        occurrence_result = self.enrich_occurrence_senses(
            source_ids, force=force
        )
        return {
            "matched": matched,
            "missing": missing,
            "occurrence_matched": occurrence_result["matched"],
            "occurrence_missing": occurrence_result["missing"],
        }

    def enrich_occurrence_senses(
        self, source_ids: Optional[Sequence[int]] = None, force: bool = False
    ) -> Dict[str, int]:
        """Refresh context-specific senses when resolver behavior changes."""
        from .dictionary import JMDictResolver

        self._sentence_learning_unit_cache.clear()

        where = "l.part_of_speech != '表現'"
        parameters: tuple = ()
        if not force:
            where += " AND COALESCE(os.dictionary_version, 0) < ?"
            parameters = (DICTIONARY_RESOLVER_VERSION,)
        if source_ids is not None:
            if not source_ids:
                return {"matched": 0, "missing": 0}
            markers = ",".join("?" for _ in source_ids)
            where += f" AND s.source_id IN ({markers})"
            parameters = (*parameters, *source_ids)
        rows = list(self.connection.execute(
            f"""SELECT os.sentence_id, os.start_char, os.end_char,
                       os.lexeme_id, l.lemma, l.reading,
                       os.part_of_speech, s.japanese, s.english
                FROM occurrence_senses os
                JOIN lexemes l ON l.id = os.lexeme_id
                JOIN sentences s ON s.id = os.sentence_id
                WHERE {where}
                ORDER BY os.sentence_id, os.start_char""",
            parameters,
        ))
        resolver = JMDictResolver()
        matched = 0
        missing = 0
        with self.transaction() as connection:
            for row in rows:
                match = resolver.resolve(
                    str(row["lemma"]), str(row["reading"]),
                    str(row["part_of_speech"]), str(row["english"] or ""),
                    strict_pos=True,
                    japanese_context=str(row["japanese"] or ""),
                    target_start=int(row["start_char"]),
                )
                status = "matched" if match is not None else "missing"
                sense_key = canonical_sense_key(
                    match.entry_id if match else None,
                    match.sense_index if match else None,
                    str(row["part_of_speech"]),
                    match.gloss if match else None,
                )
                connection.execute(
                    """UPDATE occurrence_senses
                       SET gloss = ?, dictionary_entry_id = ?,
                           dictionary_sense_index = ?, dictionary_confidence = ?,
                           dictionary_status = ?, dictionary_version = ?,
                           sense_key = ?
                       WHERE sentence_id = ? AND start_char = ? AND end_char = ?
                         AND lexeme_id = ?""",
                    (
                        match.gloss if match else None,
                        match.entry_id if match else None,
                        match.sense_index if match else None,
                        match.confidence if match else None,
                        status, DICTIONARY_RESOLVER_VERSION, sense_key,
                        row["sentence_id"], row["start_char"], row["end_char"],
                        row["lexeme_id"],
                    ),
                )
                if match is None:
                    missing += 1
                else:
                    matched += 1
        return {"matched": matched, "missing": missing}

    def mark_known(self, lexeme_key: str) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE lexemes SET known_at = COALESCE(known_at, ?) WHERE lexeme_key = ?",
                (utc_now(), lexeme_key),
            )
            if cursor.rowcount != 1:
                raise KeyError(lexeme_key)
            lexeme_id = int(connection.execute(
                "SELECT id FROM lexemes WHERE lexeme_key = ?", (lexeme_key,)
            ).fetchone()[0])
            connection.execute(
                """INSERT OR IGNORE INTO learned_senses
                   (lexeme_id, sense_key, known_at)
                   SELECT lexeme_id, sense_key, ? FROM occurrence_senses
                   WHERE lexeme_id = ? AND sense_key IS NOT NULL""",
                (utc_now(), lexeme_id),
            )

    def mark_known_by_id(self, lexeme_id: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE lexemes SET known_at = COALESCE(known_at, ?) WHERE id = ?",
                (utc_now(), lexeme_id),
            )
            connection.execute(
                """INSERT OR IGNORE INTO learned_senses
                   (lexeme_id, sense_key, known_at)
                   SELECT lexeme_id, sense_key, ? FROM occurrence_senses
                   WHERE lexeme_id = ? AND sense_key IS NOT NULL""",
                (utc_now(), lexeme_id),
            )

    def mark_sense_known(self, lexeme_id: int, sense_key: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO learned_senses (lexeme_id, sense_key, known_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(lexeme_id, sense_key) DO NOTHING""",
                (int(lexeme_id), str(sense_key), utc_now()),
            )

    def record_anki_card(
        self, lexeme_id: int, note_id: int, card_id: int, source_id: int,
        example_sentence_id: Optional[int] = None,
        sense_key: str = "legacy",
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO anki_cards
                   (lexeme_id, sense_key, note_id, card_id, introduced_source_id,
                    example_sentence_id, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(lexeme_id, sense_key) DO UPDATE SET
                     note_id=excluded.note_id,
                     card_id=excluded.card_id,
                     introduced_source_id=excluded.introduced_source_id,
                     example_sentence_id=excluded.example_sentence_id,
                     synced_at=excluded.synced_at""",
                (
                    lexeme_id, sense_key, note_id, card_id, source_id,
                    example_sentence_id, utc_now(),
                ),
            )

    def tracked_anki_cards(self) -> List[sqlite3.Row]:
        return list(self.connection.execute(
            "SELECT * FROM anki_cards ORDER BY lexeme_id, sense_key"
        ))

    def update_anki_reps(
        self, lexeme_id: int, reps: int, sense_key: str = "legacy"
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """UPDATE anki_cards SET last_seen_reps = ?, synced_at = ?
                   WHERE lexeme_id = ? AND sense_key = ?""",
                (reps, utc_now(), lexeme_id, sense_key),
            )
            if reps > 0:
                connection.execute(
                    """INSERT INTO learned_senses (lexeme_id, sense_key, known_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(lexeme_id, sense_key) DO NOTHING""",
                    (lexeme_id, sense_key, utc_now()),
                )
                if sense_key == "legacy":
                    connection.execute(
                        "UPDATE lexemes SET known_at = COALESCE(known_at, ?) WHERE id = ?",
                        (utc_now(), lexeme_id),
                    )

    def source_id(self, series: str, season: int, episode: int) -> int:
        row = self.connection.execute(
            "SELECT id FROM sources WHERE series = ? AND season = ? AND episode = ?",
            (series, season, episode),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown source: {series} S{season:02d}E{episode:02d}")
        return int(row[0])

    def source_ids(
        self, series: str, season: int, episodes: Optional[Sequence[int]] = None
    ) -> List[int]:
        if episodes is None:
            rows = self.connection.execute(
                "SELECT id FROM sources WHERE series = ? AND season = ? ORDER BY episode",
                (series, season),
            )
        else:
            if not episodes:
                return []
            markers = ",".join("?" for _ in episodes)
            rows = self.connection.execute(
                f"""SELECT id FROM sources
                    WHERE series = ? AND season = ? AND episode IN ({markers})
                    ORDER BY episode""",
                (series, season, *episodes),
            )
        return [int(row[0]) for row in rows]

    def vocabulary_growth(self, series: str, season: int) -> List[dict]:
        """Return cumulative raw and Anki-eligible vocabulary by episode."""
        episode_rows = list(self.connection.execute(
            """SELECT src.episode, COUNT(DISTINCT s.id) AS sentences
               FROM sources src
               LEFT JOIN sentences s ON s.source_id = src.id
               WHERE src.series = ? AND src.season = ?
               GROUP BY src.episode ORDER BY src.episode""",
            (series, int(season)),
        ))
        first_seen = list(self.connection.execute(
            """SELECT o.lexeme_id, MIN(src.episode) AS first_episode,
                      CASE WHEN l.dictionary_status = 'matched' AND l.gloss IS NOT NULL
                                 AND NOT (l.part_of_speech = '感動詞'
                                          AND LENGTH(l.lemma) <= 1)
                                 AND l.part_of_speech NOT IN ('接頭辞', '接尾辞')
                           THEN 1 ELSE 0 END AS eligible
               FROM occurrences o
               JOIN sentences s ON s.id = o.sentence_id
               JOIN sources src ON src.id = s.source_id
               JOIN lexemes l ON l.id = o.lexeme_id
               WHERE src.series = ? AND src.season = ?
               GROUP BY o.lexeme_id""",
            (series, int(season)),
        ))
        new_raw: Dict[int, int] = {}
        new_eligible: Dict[int, int] = {}
        for row in first_seen:
            episode = int(row["first_episode"])
            new_raw[episode] = new_raw.get(episode, 0) + 1
            if int(row["eligible"]):
                new_eligible[episode] = new_eligible.get(episode, 0) + 1
        cumulative_raw = 0
        cumulative_eligible = 0
        growth = []
        for row in episode_rows:
            episode = int(row["episode"])
            raw = new_raw.get(episode, 0)
            eligible = new_eligible.get(episode, 0)
            cumulative_raw += raw
            cumulative_eligible += eligible
            growth.append({
                "episode": episode,
                "sentences": int(row["sentences"]),
                "new_lexemes": raw,
                "new_eligible": eligible,
                "cumulative_lexemes": cumulative_raw,
                "cumulative_eligible": cumulative_eligible,
            })
        return growth

    def lexeme_labels(self, lexeme_ids: Sequence[int]) -> List[str]:
        if not lexeme_ids:
            return []
        markers = ",".join("?" for _ in lexeme_ids)
        rows = self.connection.execute(
            f"SELECT id, lemma, reading FROM lexemes WHERE id IN ({markers})",
            tuple(int(value) for value in lexeme_ids),
        )
        by_id = {
            int(row["id"]): f"{row['lemma']}（{row['reading']}）" for row in rows
        }
        return [by_id[value] for value in map(int, lexeme_ids) if value in by_id]

    def sentence_lexeme_ids(self, sentence_id: int) -> set:
        return {
            int(row[0]) for row in self.connection.execute(
                "SELECT DISTINCT lexeme_id FROM occurrences WHERE sentence_id = ?",
                (int(sentence_id),),
            )
        }

    def sentence_lexeme_spans(
        self, sentence_id: int, lexeme_id: int
    ) -> List[List[int]]:
        """Return exact lexical spans for every occurrence of a lexeme."""
        return [
            [int(row[0]), int(row[1])]
            for row in self.connection.execute(
                """SELECT start_char, end_char
                   FROM occurrence_senses
                   WHERE sentence_id = ? AND lexeme_id = ?
                     AND start_char IS NOT NULL AND end_char IS NOT NULL
                   ORDER BY start_char, end_char""",
                (int(sentence_id), int(lexeme_id)),
            )
        ]

    def sentence_learning_unit_keys(self, sentence_id: int) -> set:
        """Return every lexical dependency without double-counting expressions.

        Persisted occurrence senses are the preferred, sense-aware analysis. A
        database created by an older tokenizer can nevertheless omit a tracked
        component (notably noun-like suffixes such as 官 in 試験官). Retokenize
        the sentence with the current component tokenizer and add only tokens
        that are not covered by a persisted span. Persisted multi-token spans
        therefore remain one atomic unit, while gaps can never disappear from
        the progressive unknown-word gate.
        """
        sentence_id = int(sentence_id)
        cached = self._sentence_learning_unit_cache.get(sentence_id)
        if cached is not None:
            return set(cached)

        rows = list(self.connection.execute(
            """SELECT os.start_char, os.end_char, os.sense_key,
                      l.lexeme_key
               FROM occurrence_senses os
               JOIN lexemes l ON l.id = os.lexeme_id
               WHERE os.sentence_id = ? AND os.sense_key IS NOT NULL
               ORDER BY os.start_char, os.end_char""",
            (sentence_id,),
        ))
        # A retained whole-expression occurrence is authoritative over any
        # component occurrence nested inside it. Partially overlapping spans
        # remain separate dependencies; neither may hide the other.
        rows = [
            row for row in rows
            if not any(
                (
                    int(other["start_char"]) <= int(row["start_char"])
                    and int(row["end_char"]) <= int(other["end_char"])
                    and (
                        int(other["start_char"]) < int(row["start_char"])
                        or int(row["end_char"]) < int(other["end_char"])
                    )
                )
                for other in rows
            )
        ]
        keys = {
            learning_unit_key(str(row["lexeme_key"]), str(row["sense_key"]))
            for row in rows
        }
        covered_spans = [
            (int(row["start_char"]), int(row["end_char"])) for row in rows
        ]
        sentence = self.connection.execute(
            "SELECT japanese, english FROM sentences WHERE id = ?",
            (sentence_id,),
        ).fetchone()
        if sentence is not None:
            from .dictionary import JMDictResolver
            from .tokenizer import JapaneseTokenizer

            resolver = JMDictResolver()
            for token in JapaneseTokenizer().tokenize(str(sentence["japanese"])):
                if any(
                    start <= token.start and token.end <= end
                    for start, end in covered_spans
                ):
                    continue
                match = resolver.resolve(
                    token.lemma,
                    token.reading,
                    token.part_of_speech,
                    str(sentence["english"] or ""),
                    strict_pos=True,
                    japanese_context=str(sentence["japanese"]),
                    target_start=token.start,
                )
                sense_key = canonical_sense_key(
                    match.entry_id if match else None,
                    match.sense_index if match else None,
                    token.part_of_speech,
                    match.gloss if match else None,
                )
                keys.add(learning_unit_key(token.key, sense_key))

        self._sentence_learning_unit_cache[sentence_id] = set(keys)
        return keys

    def occurrence_candidates_for_targets(
        self,
        target_rows: Sequence[Mapping[str, object]],
        source_ids: Sequence[int],
        *,
        candidates_per_target: int = 5,
    ) -> List[dict]:
        """Materialize several source examples without changing target order.

        Target vocabulary is frozen by ``target_rows``. Candidate ranking may
        choose a different sentence, but it cannot replace a target with an
        easier-to-validate word.
        """
        from .progression import example_score
        from .dictionary import JMDictResolver
        from .tokenizer import JapaneseTokenizer

        if candidates_per_target < 1:
            raise ValueError("candidates per target must be positive")
        if not source_ids:
            return []
        markers = ",".join("?" for _ in source_ids)
        tokenizer = JapaneseTokenizer()
        contextual_resolver = JMDictResolver()
        initial_known_ids = {
            int(row[0]) for row in self.connection.execute(
                "SELECT id FROM lexemes WHERE known_at IS NOT NULL"
            )
        }
        initial_known_units = {
            learning_unit_key(str(row["lexeme_key"]), str(row["sense_key"]))
            for row in self.connection.execute(
                """SELECT l.lexeme_key, learned.sense_key
                   FROM learned_senses learned
                   JOIN lexemes l ON l.id = learned.lexeme_id"""
            )
        }
        known_ids = set(initial_known_ids)
        lexical_difficulties = {
            int(row["lexeme_id"]): float(row.get("difficulty_score") or 0.0)
            for row in target_rows
        }
        materialized: List[dict] = []
        for curriculum_index, raw_target in enumerate(target_rows):
            target = dict(raw_target)
            lexeme_id = int(target["lexeme_id"])
            target_entry_id = target.get("dictionary_entry_id")
            target_sense_index = target.get("dictionary_sense_index")
            rows = self.connection.execute(
                f"""SELECT s.id AS sentence_id, s.japanese, s.english,
                           s.start_ms, s.end_ms, s.source_id, s.cue_index,
                           src.series, src.season, src.episode, src.video_path,
                           target_occurrence.surface,
                           sense.start_char AS occurrence_start,
                           sense.end_char AS occurrence_end,
                           sense.part_of_speech AS contextual_part_of_speech,
                           sense.gloss AS contextual_gloss,
                           sense.dictionary_entry_id AS contextual_dictionary_entry_id,
                           sense.dictionary_sense_index AS contextual_dictionary_sense_index,
                           sense.dictionary_confidence AS contextual_dictionary_confidence,
                           sense.dictionary_status AS contextual_dictionary_status,
                           sense.sense_key AS contextual_sense_key,
                           GROUP_CONCAT(DISTINCT all_words.lexeme_id) AS word_ids_csv
                    FROM occurrences target_occurrence
                    LEFT JOIN occurrence_senses sense
                      ON sense.lexeme_id = target_occurrence.lexeme_id
                     AND sense.sentence_id = target_occurrence.sentence_id
                     AND sense.surface = target_occurrence.surface
                    JOIN sentences s ON s.id = target_occurrence.sentence_id
                    JOIN sources src ON src.id = s.source_id
                    JOIN occurrences all_words ON all_words.sentence_id = s.id
                    WHERE target_occurrence.lexeme_id = ?
                      AND sense.dictionary_entry_id = ?
                      AND sense.dictionary_sense_index = ?
                      AND s.source_id IN ({markers})
                    GROUP BY s.id, sense.start_char, sense.end_char,
                             target_occurrence.lexeme_id, target_occurrence.surface""",
                (lexeme_id, target_entry_id, target_sense_index, *source_ids),
            )
            ranked_examples = []
            for raw_candidate in rows:
                candidate = dict(raw_candidate)
                word_ids = {
                    int(value)
                    for value in str(candidate.pop("word_ids_csv") or "").split(",")
                    if value
                }
                candidate["word_ids"] = word_ids
                candidate["context_learning_unit_keys"] = sorted(
                    self.sentence_learning_unit_keys(
                        int(candidate["sentence_id"])
                    )
                )
                candidate["lemma"] = str(target["lemma"])
                if str(target.get("part_of_speech") or "") != "表現":
                    contextual_match = contextual_resolver.resolve(
                        str(target["lemma"]), str(target["reading"]),
                        str(
                            candidate.get("contextual_part_of_speech")
                            or target.get("part_of_speech") or ""
                        ),
                        str(candidate.get("english") or ""),
                        strict_pos=True,
                        japanese_context=str(candidate.get("japanese") or ""),
                        target_start=(
                            int(candidate["occurrence_start"])
                            if candidate.get("occurrence_start") is not None
                            else None
                        ),
                    )
                    if contextual_match is not None:
                        if (
                            contextual_match.entry_id != int(target_entry_id)
                            or contextual_match.sense_index
                            != int(target_sense_index)
                        ):
                            continue
                        candidate.update({
                            "contextual_gloss": contextual_match.gloss,
                            "contextual_dictionary_entry_id": (
                                contextual_match.entry_id
                            ),
                            "contextual_dictionary_sense_index": (
                                contextual_match.sense_index
                            ),
                            "contextual_dictionary_confidence": (
                                contextual_match.confidence
                            ),
                            "contextual_dictionary_status": "matched",
                        })
                occurrence_start = candidate.pop("occurrence_start")
                occurrence_end = candidate.pop("occurrence_end")
                if occurrence_start is not None and occurrence_end is not None:
                    candidate["target_lexical_start"] = int(occurrence_start)
                    candidate["target_lexical_end"] = int(occurrence_end)
                candidate["target_lexical_spans"] = self.sentence_lexeme_spans(
                    int(candidate["sentence_id"]), lexeme_id
                )
                span = tokenizer.find_inflected_span(
                    str(candidate["japanese"]), str(target["lemma"]),
                    str(target["reading"]), str(candidate["surface"]),
                )
                if not span:
                    continue
                candidate["target_start"], candidate["target_end"] = span
                candidate.setdefault("target_lexical_start", span[0])
                candidate.setdefault(
                    "target_lexical_end", span[0] + len(str(candidate["surface"]))
                )
                candidate["target_surface"] = str(candidate["japanese"])[
                    span[0]:span[1]
                ]
                score, progression = example_score(
                    candidate, lexeme_id, known_ids, curriculum_index,
                    lexical_difficulties,
                    float(target.get("difficulty_score") or 0.0),
                )
                ranked_examples.append((score, int(candidate["cue_index"]), candidate, progression))
            ranked_examples.sort(key=lambda item: (item[0], item[1]))
            for candidate_index, (_, _, candidate, progression) in enumerate(
                ranked_examples[:candidates_per_target], start=1
            ):
                card = dict(target)
                for field in (
                    "sentence_id", "japanese", "english", "start_ms", "end_ms",
                    "source_id", "cue_index", "series", "season", "episode",
                    "video_path", "target_surface", "target_start", "target_end",
                    "target_lexical_start", "target_lexical_end",
                    "target_lexical_spans",
                    "contextual_part_of_speech", "contextual_gloss",
                    "contextual_dictionary_entry_id",
                    "contextual_dictionary_sense_index",
                    "contextual_dictionary_confidence",
                    "contextual_dictionary_status",
                    "contextual_sense_key",
                ):
                    card[field] = candidate.get(field)
                card["sentence_word_count"] = len(candidate["word_ids"])
                card["sentence_unknown_word_count"] = (
                    int(progression["unknown_other_words"]) + 1
                )
                card["global_part_of_speech"] = target.get("part_of_speech")
                if (
                    card.get("contextual_dictionary_status") == "matched"
                    and card.get("contextual_part_of_speech")
                    == card.get("part_of_speech")
                ):
                    card["gloss"] = card.get("contextual_gloss")
                    card["dictionary_entry_id"] = card.get(
                        "contextual_dictionary_entry_id"
                    )
                    card["dictionary_sense_index"] = card.get(
                        "contextual_dictionary_sense_index"
                    )
                    card["dictionary_confidence"] = card.get(
                        "contextual_dictionary_confidence"
                    )
                card["example_progression"] = progression
                card["context_lexeme_ids"] = sorted(candidate["word_ids"])
                card["context_learning_unit_keys"] = list(
                    candidate["context_learning_unit_keys"]
                )
                target_unit = str(card["learning_unit_key"])
                card["initial_known_context_learning_unit_keys"] = sorted(
                    (
                        set(candidate["context_learning_unit_keys"])
                        - {target_unit}
                    ) & initial_known_units
                )
                card["initial_unknown_context_learning_unit_keys"] = sorted(
                    set(candidate["context_learning_unit_keys"])
                    - {target_unit}
                    - initial_known_units
                )
                card["initial_known_context_lexeme_ids"] = sorted(
                    (candidate["word_ids"] - {lexeme_id}) & initial_known_ids
                )
                card["initial_unknown_context_lexeme_ids"] = sorted(
                    candidate["word_ids"] - {lexeme_id} - initial_known_ids
                )
                card["curriculum_position"] = curriculum_index + 1
                card["candidate_position"] = candidate_index
                card["candidate_key"] = ":".join((
                    str(card["learning_unit_key"]), str(card["sentence_id"]),
                    str(card.get("target_lexical_start")),
                    str(card.get("target_lexical_end")),
                ))
                materialized.append(card)
            known_ids.add(lexeme_id)
        return materialized

    def fully_known_alternative_examples(
        self,
        row: Mapping[str, object],
        source_ids: Sequence[int],
        known_ids: set,
        used_sentence_ids: set,
    ) -> List[dict]:
        """Return unused occurrences whose context is already fully known."""
        from .tokenizer import JapaneseTokenizer

        if not source_ids:
            return []
        markers = ",".join("?" for _ in source_ids)
        candidates = list(self.connection.execute(
            f"""SELECT s.id AS sentence_id, s.japanese, s.english,
                       s.start_ms, s.end_ms, s.source_id, s.cue_index,
                       src.series, src.season, src.episode, src.video_path,
                       target_occurrence.surface,
                       target.start_char AS occurrence_start,
                       target.end_char AS occurrence_end,
                       target.part_of_speech AS contextual_part_of_speech,
                       target.gloss AS contextual_gloss,
                       target.dictionary_entry_id AS contextual_dictionary_entry_id,
                       target.dictionary_sense_index AS contextual_dictionary_sense_index,
                       target.dictionary_confidence AS contextual_dictionary_confidence,
                       target.dictionary_status AS contextual_dictionary_status,
                       GROUP_CONCAT(DISTINCT all_words.lexeme_id) AS word_ids_csv
                FROM occurrences target_occurrence
                LEFT JOIN occurrence_senses target
                  ON target.lexeme_id = target_occurrence.lexeme_id
                 AND target.sentence_id = target_occurrence.sentence_id
                 AND target.surface = target_occurrence.surface
                JOIN sentences s ON s.id = target_occurrence.sentence_id
                JOIN sources src ON src.id = s.source_id
                JOIN occurrences all_words ON all_words.sentence_id = s.id
                WHERE target_occurrence.lexeme_id = ?
                  AND s.source_id IN ({markers})
                GROUP BY s.id, target.start_char, target.end_char,
                         target_occurrence.lexeme_id, target_occurrence.surface
                ORDER BY CASE WHEN s.english IS NULL OR s.english = '' THEN 1 ELSE 0 END,
                         LENGTH(s.japanese), s.cue_index""",
            (int(row["lexeme_id"]), *source_ids),
        ))
        tokenizer = JapaneseTokenizer()
        alternatives = []
        for candidate_row in candidates:
            candidate = dict(candidate_row)
            sentence_id = int(candidate["sentence_id"])
            if sentence_id in used_sentence_ids or sentence_id == int(row["sentence_id"]):
                continue
            word_ids = {
                int(value) for value in candidate.pop("word_ids_csv").split(",")
            }
            other_ids = word_ids - {int(row["lexeme_id"])}
            if other_ids - known_ids:
                continue
            lexical_surface = str(candidate["surface"])
            occurrence_start = candidate.pop("occurrence_start")
            occurrence_end = candidate.pop("occurrence_end")
            if occurrence_start is not None and occurrence_end is not None:
                candidate["target_lexical_start"] = int(occurrence_start)
                candidate["target_lexical_end"] = int(occurrence_end)
            candidate["target_lexical_spans"] = self.sentence_lexeme_spans(
                sentence_id, int(row["lexeme_id"])
            )
            span = tokenizer.find_inflected_span(
                str(candidate["japanese"]), str(row["lemma"]),
                str(row["reading"]), lexical_surface,
            )
            if not span:
                continue
            candidate["target_start"], candidate["target_end"] = span
            candidate.setdefault("target_lexical_start", span[0])
            candidate.setdefault(
                "target_lexical_end", span[0] + len(lexical_surface)
            )
            candidate["target_surface"] = str(candidate["japanese"])[span[0]:span[1]]
            candidate["sentence_word_count"] = len(word_ids)
            candidate["sentence_unknown_word_count"] = 1
            global_pos = str(
                row.get("global_part_of_speech")
                or row.get("part_of_speech") or ""
            )
            if (
                candidate.get("contextual_dictionary_status") == "matched"
                and candidate.get("contextual_part_of_speech") == global_pos
            ):
                candidate["gloss"] = candidate.get("contextual_gloss")
                candidate["dictionary_entry_id"] = candidate.get(
                    "contextual_dictionary_entry_id"
                )
                candidate["dictionary_sense_index"] = candidate.get(
                    "contextual_dictionary_sense_index"
                )
                candidate["dictionary_confidence"] = candidate.get(
                    "contextual_dictionary_confidence"
                )
            candidate["example_progression"] = {
                "content_words": len(word_ids),
                "unknown_other_words": 0,
                "unknown_other_ids": [],
                "harder_unknown_words": 0,
                "harder_unknown_ids": [],
            }
            alternatives.append(candidate)
        return alternatives

    def expression_analyses_for_sentence(
        self, sentence_id: Optional[int]
    ) -> List[sqlite3.Row]:
        if sentence_id is None:
            return []
        return list(self.connection.execute(
            """SELECT * FROM expression_analyses
               WHERE sentence_id = ? ORDER BY start_char, end_char""",
            (int(sentence_id),),
        ))

    def excluded_candidates(
        self, source_ids: Sequence[int], limit: int = 100
    ) -> List[dict]:
        if not source_ids:
            return []
        markers = ",".join("?" for _ in source_ids)
        rows = self.connection.execute(
            f"""WITH excluded AS (
                   SELECT l.id AS lexeme_id, l.lexeme_key, l.lemma, l.reading,
                          l.part_of_speech, l.gloss, l.dictionary_status,
                          s.id AS sentence_id, s.japanese, s.english,
                          src.series, src.season, src.episode,
                          SUM(o.count) OVER (PARTITION BY l.id) AS source_count,
                          ROW_NUMBER() OVER (
                            PARTITION BY l.id
                            ORDER BY CASE WHEN s.english IS NULL OR s.english = ''
                                          THEN 1 ELSE 0 END,
                                     LENGTH(s.japanese), s.cue_index
                          ) AS occurrence_rank,
                          CASE
                            WHEN l.part_of_speech = '感動詞' AND LENGTH(l.lemma) <= 1
                              THEN 'reaction_fragment'
                            ELSE 'missing_definition'
                          END AS exclusion_reason
                   FROM lexemes l
                   JOIN occurrences o ON o.lexeme_id = l.id
                   JOIN sentences s ON s.id = o.sentence_id
                   JOIN sources src ON src.id = s.source_id
                   WHERE s.source_id IN ({markers})
                     AND (
                       l.dictionary_status = 'missing' OR l.gloss IS NULL
                       OR (l.part_of_speech = '感動詞' AND LENGTH(l.lemma) <= 1)
                     )
                 )
                 SELECT * FROM excluded WHERE occurrence_rank = 1
                 ORDER BY source_count DESC, lemma LIMIT ?""",
            (*source_ids, int(limit)),
        )
        return [dict(row) for row in rows]

    def stats(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for name, sql in {
            "sources": "SELECT COUNT(*) FROM sources",
            "lexemes": "SELECT COUNT(*) FROM lexemes",
            "known": "SELECT COUNT(*) FROM lexemes WHERE known_at IS NOT NULL",
            "learned_senses": "SELECT COUNT(*) FROM learned_senses",
            "lexemes_with_learned_senses": (
                "SELECT COUNT(DISTINCT lexeme_id) FROM learned_senses"
            ),
            "sentences": "SELECT COUNT(*) FROM sentences",
        }.items():
            result[name] = int(self.connection.execute(sql).fetchone()[0])
        return result
