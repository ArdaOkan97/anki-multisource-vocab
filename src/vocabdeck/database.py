from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

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

CREATE TABLE IF NOT EXISTS source_queue (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    lexeme_id INTEGER NOT NULL REFERENCES lexemes(id) ON DELETE CASCADE,
    rank_score REAL NOT NULL,
    example_sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    PRIMARY KEY(source_id, lexeme_id)
);

CREATE TABLE IF NOT EXISTS anki_cards (
    lexeme_id INTEGER PRIMARY KEY REFERENCES lexemes(id) ON DELETE CASCADE,
    note_id INTEGER NOT NULL UNIQUE,
    card_id INTEGER,
    introduced_source_id INTEGER REFERENCES sources(id),
    last_seen_reps INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VocabularyDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

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
        }
        for name, sql_type in additions.items():
            if name not in existing:
                self.connection.execute(f"ALTER TABLE lexemes ADD COLUMN {name} {sql_type}")
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
        sentence_count = 0
        occurrence_count = 0
        with self.transaction() as connection:
            # Queue rows point at selected example sentences, so remove them before
            # replacing an episode's sentence set.
            connection.execute("DELETE FROM source_queue WHERE source_id = ?", (source_id,))
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
                for token in tokenizer.tokenize(cue.text):
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
                    connection.execute(
                        """INSERT INTO occurrences (lexeme_id, sentence_id, surface, count)
                           VALUES (?, ?, ?, ?)""",
                        (lexeme_id, sentence_id, token.surface, count),
                    )
                    occurrence_count += count
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

    def next_unseen_for_sources(
        self, source_ids: Sequence[int], limit: int = 20, metric: str = "hybrid"
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
        # Joint planning over a bounded lexical shortlist keeps batch generation
        # responsive without allowing a rare word with a trivial subtitle to
        # leapfrog arbitrarily far ahead of broadly useful vocabulary.
        pool_size = min(len(ranked), max(100, limit * 5))
        return self._plan_progressive_batch(ranked[:pool_size], source_ids, limit)

    def _plan_progressive_batch(
        self, rows: List[dict], source_ids: Sequence[int], limit: int
    ) -> List[dict]:
        from .progression import example_score, joint_planning_score
        from .tokenizer import JapaneseTokenizer

        if not rows:
            return rows
        known_ids = {
            int(row[0]) for row in self.connection.execute(
                "SELECT id FROM lexemes WHERE known_at IS NOT NULL"
            )
        }
        markers = ",".join("?" for _ in source_ids)
        tokenizer = JapaneseTokenizer()
        examples_by_lexeme: Dict[int, List[dict]] = {}

        def load_examples(row: dict) -> List[dict]:
            lexeme_id = int(row["lexeme_id"])
            if lexeme_id in examples_by_lexeme:
                return examples_by_lexeme[lexeme_id]
            example_rows = list(
                self.connection.execute(
                    f"""SELECT s.id AS sentence_id, s.japanese, s.english,
                               s.start_ms, s.end_ms, s.source_id, s.cue_index,
                               src.series, src.season, src.episode, src.video_path,
                               target.surface,
                               GROUP_CONCAT(DISTINCT all_words.lexeme_id) AS word_ids_csv
                        FROM occurrences target
                        JOIN sentences s ON s.id = target.sentence_id
                        JOIN sources src ON src.id = s.source_id
                        JOIN occurrences all_words ON all_words.sentence_id = s.id
                        WHERE target.lexeme_id = ? AND s.source_id IN ({markers})
                        GROUP BY s.id, target.surface""",
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
                span = tokenizer.find_inflected_span(
                    candidate["japanese"], row["lemma"], row["reading"],
                    candidate["surface"],
                )
                if span:
                    candidate["target_start"], candidate["target_end"] = span
                    candidate["surface"] = candidate["japanese"][span[0]:span[1]]
                examples.append(candidate)
            examples_by_lexeme[lexeme_id] = examples
            return examples

        remaining = list(rows)
        selected = []
        for position in range(min(limit, len(remaining))):
            best_plan = None
            for rank_index, row in enumerate(remaining):
                best_example = None
                for candidate in load_examples(row):
                    score, details = example_score(
                        candidate, int(row["lexeme_id"]), known_ids, position
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
            if best_plan is None:
                break
            _, _, rank_index, row, candidate, details, planner = best_plan
            remaining.pop(rank_index)
            for field in (
                "japanese", "english", "start_ms", "end_ms", "source_id",
                "cue_index", "series", "season", "episode", "video_path",
            ):
                row[field] = candidate[field]
            row["sentence_word_count"] = len(candidate["word_ids"])
            row["sentence_unknown_word_count"] = details["unknown_other_words"] + 1
            row["target_surface"] = candidate["surface"]
            row["target_start"] = candidate.get("target_start")
            row["target_end"] = candidate.get("target_end")
            row["example_progression"] = details
            row["batch_planning"] = planner
            selected.append(row)
            known_ids.add(int(row["lexeme_id"]))
        return selected

    def enrich_dictionary(
        self, source_ids: Optional[Sequence[int]] = None, force: bool = False
    ) -> Dict[str, int]:
        from .dictionary import JMDictResolver

        where = "1 = 1" if force else "l.dictionary_status IS NULL"
        parameters: tuple = ()
        if source_ids is not None:
            if not source_ids:
                return {"matched": 0, "missing": 0}
            markers = ",".join("?" for _ in source_ids)
            where += (
                " AND EXISTS (SELECT 1 FROM occurrences ox "
                "JOIN sentences sx ON sx.id = ox.sentence_id "
                f"WHERE ox.lexeme_id = l.id AND sx.source_id IN ({markers}))"
            )
            parameters = tuple(source_ids)
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
                                  dictionary_status = 'missing' WHERE id = ?""",
                        (row["id"],),
                    )
                    missing += 1
                else:
                    connection.execute(
                        """UPDATE lexemes SET gloss = ?, dictionary_entry_id = ?,
                                  dictionary_sense_index = ?, dictionary_confidence = ?,
                                  dictionary_status = 'matched' WHERE id = ?""",
                        (
                            match.gloss, match.entry_id, match.sense_index,
                            match.confidence, row["id"],
                        ),
                    )
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

    def mark_known_by_id(self, lexeme_id: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE lexemes SET known_at = COALESCE(known_at, ?) WHERE id = ?",
                (utc_now(), lexeme_id),
            )

    def record_anki_card(
        self, lexeme_id: int, note_id: int, card_id: int, source_id: int
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO anki_cards
                   (lexeme_id, note_id, card_id, introduced_source_id, synced_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(lexeme_id) DO UPDATE SET
                     note_id=excluded.note_id,
                     card_id=excluded.card_id,
                     introduced_source_id=excluded.introduced_source_id,
                     synced_at=excluded.synced_at""",
                (lexeme_id, note_id, card_id, source_id, utc_now()),
            )

    def tracked_anki_cards(self) -> List[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM anki_cards ORDER BY lexeme_id"))

    def update_anki_reps(self, lexeme_id: int, reps: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                """UPDATE anki_cards SET last_seen_reps = ?, synced_at = ?
                   WHERE lexeme_id = ?""",
                (reps, utc_now(), lexeme_id),
            )
            if reps > 0:
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

    def stats(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for name, sql in {
            "sources": "SELECT COUNT(*) FROM sources",
            "lexemes": "SELECT COUNT(*) FROM lexemes",
            "known": "SELECT COUNT(*) FROM lexemes WHERE known_at IS NOT NULL",
            "sentences": "SELECT COUNT(*) FROM sentences",
        }.items():
            result[name] = int(self.connection.execute(sql).fetchone()[0])
        return result
