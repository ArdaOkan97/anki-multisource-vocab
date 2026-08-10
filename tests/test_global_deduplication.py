import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vocabdeck.database import VocabularyDatabase
from vocabdeck.anki import sync_source
from vocabdeck.progression import example_score
from vocabdeck.semantics import ExpressionDecision
from vocabdeck.subtitles import Cue
from vocabdeck.tokenizer import JapaneseTokenizer, LexemeToken


class CharacterTokenizer:
    def tokenize(self, text):
        return [LexemeToken(char, char, char, "名詞") for char in text.replace(" ", "")]


class FixedExpressionScorer:
    def __init__(self, decision):
        self.decision = decision

    def decide(
        self, english, phrase_senses, component_glosses, standalone=False
    ):
        phrase_score = 0.95 if self.decision == "expression" else 0.20
        component_score = 0.20 if self.decision == "expression" else 0.95
        return ExpressionDecision(
            decision=self.decision,
            phrase_score=phrase_score,
            component_score=component_score,
            margin=phrase_score - component_score,
            opacity=0.80,
            phrase_description=phrase_senses[0],
            component_description=" | ".join(component_glosses),
            model="test-embedder",
        )


class FakeAnkiConnect:
    def __init__(self):
        self.next_note = 100
        self.notes = {}
        self.cards = {}

    def ensure_model(self):
        pass

    def ensure_deck(self, deck):
        pass

    def invoke(self, action, **params):
        if action == "cardsInfo":
            return [
                {"cardId": card_id, "reps": self.cards[card_id]["reps"]}
                for card_id in params["cards"] if card_id in self.cards
            ]
        if action == "addNote":
            note_id = self.next_note
            self.next_note += 1
            card_id = note_id + 1000
            note = params["note"]
            self.notes[note_id] = note
            self.cards[card_id] = {"note_id": note_id, "deck": note["deckName"], "reps": 0}
            return note_id
        if action == "findCards":
            note_id = int(params["query"].split(":", 1)[1])
            return [card_id for card_id, card in self.cards.items() if card["note_id"] == note_id]
        if action == "updateNoteFields":
            note = params["note"]
            self.notes[note["id"]]["fields"] = note["fields"]
            return None
        if action == "changeDeck":
            for card_id in params["cards"]:
                self.cards[card_id]["deck"] = params["deck"]
            return None
        raise AssertionError(f"Unexpected action: {action}")

    def set_reps_for_expression(self, expressions, reps=1):
        for card in self.cards.values():
            note = self.notes[card["note_id"]]
            if note["fields"]["Expression"] in expressions:
                card["reps"] = reps


class GlobalDeduplicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = VocabularyDatabase(Path(self.temp.name) / "state.sqlite3")
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add_show(self, name, words):
        source_id = self.db.add_source(
            series=name,
            season=1,
            episode=1,
            title=None,
            video_path=None,
            japanese_subtitle_path=f"{name}.srt",
            english_subtitle_path=None,
        )
        cues = [Cue(i, i * 1000, i * 1000 + 800, word) for i, word in enumerate(words, 1)]
        self.db.ingest_cues(source_id, cues, [], CharacterTokenizer())
        return source_id

    def keys_by_lemma(self):
        rows = self.db.connection.execute("SELECT lemma, lexeme_key FROM lexemes")
        return {row["lemma"]: row["lexeme_key"] for row in rows}

    def queue_lemmas(self, source_id):
        return [row["lemma"] for row in self.db.next_unseen(source_id, 100)]

    def test_hxh_naruto_hxh_handoff(self):
        hxh = self.add_show("Hunter x Hunter", list("ABCDEFXY"))
        naruto = self.add_show("Naruto", list("CEFGH"))
        keys = self.keys_by_lemma()

        for word in "ABCDE":
            self.db.mark_known(keys[word])
        self.assertEqual(self.queue_lemmas(naruto), list("FGH"))

        for word in "FGH":
            self.db.mark_known(keys[word])
        self.assertEqual(self.queue_lemmas(hxh), list("XY"))
        self.assertEqual(self.db.stats()["known"], 8)
        self.assertEqual(self.db.stats()["lexemes"], 10)

    def test_reimport_is_idempotent(self):
        source = self.add_show("Show", ["猫", "猫"])
        self.assertEqual(self.db.stats()["lexemes"], 1)
        self.assertEqual(self.db.connection.execute("SELECT corpus_count FROM lexemes").fetchone()[0], 2)

        cues = [Cue(1, 0, 800, "猫"), Cue(2, 1000, 1800, "猫")]
        self.db.ingest_cues(source, cues, [], CharacterTokenizer())
        self.assertEqual(self.db.connection.execute("SELECT corpus_count FROM lexemes").fetchone()[0], 2)

    def test_episode_range_forms_one_queue(self):
        episode_1 = self.add_show("Range Show", ["猫"])
        source_2 = self.db.add_source(
            series="Range Show", season=1, episode=2, title=None, video_path=None,
            japanese_subtitle_path="2.srt", english_subtitle_path=None,
        )
        self.db.ingest_cues(
            source_2, [Cue(1, 0, 800, "犬")], [], CharacterTokenizer()
        )
        rows = self.db.next_unseen_for_sources([episode_1, source_2], 10)
        self.assertEqual({row["lemma"] for row in rows}, {"猫", "犬"})

    def test_same_lemma_and_reading_merge_across_grammatical_roles(self):
        noun = LexemeToken("そう", "そう", "ソウ", "名詞")
        adverb = LexemeToken("そう", "そう", "ソウ", "副詞")
        self.assertEqual(noun.key, adverb.key)

    def test_pronoun_occurrence_counts_as_unknown_sentence_context(self):
        source = self.db.add_source(
            series="Pronoun Show", season=1, episode=1, title=None,
            video_path=None, japanese_subtitle_path="pronoun.srt",
            english_subtitle_path=None,
        )
        self.db.ingest_cues(
            source,
            [Cue(1, 0, 1000, "何を思う？")],
            [Cue(1, 0, 1000, "What do you think?")],
            JapaneseTokenizer(),
        )
        lexemes = {
            row["lemma"]: int(row["id"])
            for row in self.db.connection.execute(
                "SELECT id, lemma FROM lexemes WHERE lemma IN ('何', '思う')"
            )
        }
        self.assertEqual(set(lexemes), {"何", "思う"})
        sentence = self.db.connection.execute(
            "SELECT id, japanese, english FROM sentences WHERE source_id = ?", (source,)
        ).fetchone()
        word_ids = {
            int(row[0]) for row in self.db.connection.execute(
                "SELECT DISTINCT lexeme_id FROM occurrences WHERE sentence_id = ?",
                (sentence["id"],),
            )
        }
        _, details = example_score(
            {
                "word_ids": word_ids, "japanese": sentence["japanese"],
                "english": sentence["english"], "surface": "思う", "lemma": "思う",
            },
            lexemes["思う"], set(), position=0,
        )
        self.assertEqual(details["content_words"], 2)
        self.assertEqual(details["unknown_other_words"], 1)

    def test_expression_ingestion_does_not_count_opaque_component(self):
        source = self.db.add_source(
            series="Expression Show", season=1, episode=1, title=None,
            video_path=None, japanese_subtitle_path="expression.srt",
            english_subtitle_path=None,
        )
        self.db.ingest_cues(
            source,
            [Cue(1, 0, 1000, "どうも。"), Cue(2, 1000, 2000, "どうする？")],
            [Cue(1, 0, 1000, "Thank you."), Cue(2, 1000, 2000, "What will you do?")],
            JapaneseTokenizer(
                expression_scorer=FixedExpressionScorer("expression")
            ),
        )

        occurrences = {
            (row["lemma"], row["japanese"])
            for row in self.db.connection.execute(
                """SELECT l.lemma, s.japanese FROM occurrences o
                   JOIN lexemes l ON l.id = o.lexeme_id
                   JOIN sentences s ON s.id = o.sentence_id
                   WHERE s.source_id = ?""",
                (source,),
            )
        }

        self.assertIn(("どうも", "どうも。"), occurrences)
        self.assertNotIn(("どう", "どうも。"), occurrences)
        self.assertIn(("どう", "どうする？"), occurrences)
        self.assertIn(("する", "どうする？"), occurrences)
        analysis = self.db.connection.execute(
            """SELECT decision, model FROM expression_analyses
               WHERE sentence_id = (
                 SELECT id FROM sentences WHERE source_id = ? AND cue_index = 1
               ) AND surface = 'どうも'""",
            (source,),
        ).fetchone()
        self.assertEqual((analysis["decision"], analysis["model"]), (
            "expression", "test-embedder"
        ))

    def test_rejected_expression_keeps_component_occurrences(self):
        source = self.db.add_source(
            series="Literal Show", season=1, episode=1, title=None,
            video_path=None, japanese_subtitle_path="literal.srt",
            english_subtitle_path=None,
        )
        self.db.ingest_cues(
            source,
            [Cue(1, 0, 1000, "いい顔だぁ！")],
            [Cue(1, 0, 1000, "I really do love that look.")],
            JapaneseTokenizer(
                expression_scorer=FixedExpressionScorer("components")
            ),
        )
        lemmas = {
            row[0] for row in self.db.connection.execute(
                """SELECT l.lemma FROM occurrences o
                   JOIN lexemes l ON l.id = o.lexeme_id
                   JOIN sentences s ON s.id = o.sentence_id
                   WHERE s.source_id = ?""",
                (source,),
            )
        }
        self.assertIn("いい", lemmas)
        self.assertIn("顔", lemmas)
        self.assertNotIn("いい顔", lemmas)

    def test_planner_prefers_an_easier_unknown_context_word(self):
        source = self.add_show("Difficulty Show", ["AB", "AC"])
        fixed_difficulties = {"A": 20.0, "B": 10.0, "C": 50.0}

        def rank_with_fixed_difficulty(rows, metric):
            ranked = []
            for raw_row in rows:
                row = dict(raw_row)
                row["difficulty_score"] = fixed_difficulties[row["lemma"]]
                row["difficulty_metric"] = metric
                ranked.append(row)
            return ranked

        with patch("vocabdeck.difficulty.rank_candidates", rank_with_fixed_difficulty):
            rows = self.db.next_unseen(source, limit=1)

        self.assertEqual(rows[0]["lemma"], "A")
        self.assertIsInstance(rows[0]["sentence_id"], int)
        self.assertEqual(rows[0]["japanese"], "AB")
        self.assertEqual(rows[0]["example_progression"]["harder_unknown_words"], 0)

    def test_queue_excludes_missing_definitions_and_single_kana_reactions(self):
        source = self.db.add_source(
            series="Eligibility Show", season=1, episode=1, title=None,
            video_path=None, japanese_subtitle_path="eligibility.srt",
            english_subtitle_path=None,
        )

        class EligibilityTokenizer:
            def tokenize(self, text):
                values = {
                    "う": LexemeToken("う", "う", "ウ", "感動詞"),
                    "なっ": LexemeToken("なっ", "なっ", "ナッ", "感動詞"),
                    "猫": LexemeToken("猫", "猫", "ネコ", "名詞"),
                }
                return [values[text]]

        self.db.ingest_cues(
            source,
            [Cue(1, 0, 800, "う"), Cue(2, 1000, 1800, "なっ"),
             Cue(3, 2000, 2800, "猫")],
            [], EligibilityTokenizer(),
        )
        self.db.connection.execute(
            """UPDATE lexemes SET gloss = 'rabbit', dictionary_status = 'matched'
               WHERE lemma = 'う'"""
        )
        self.db.connection.execute(
            "UPDATE lexemes SET dictionary_status = 'missing' WHERE lemma = 'なっ'"
        )
        self.db.connection.execute(
            """UPDATE lexemes SET gloss = 'cat', dictionary_status = 'matched'
               WHERE lemma = '猫'"""
        )
        self.db.connection.commit()

        self.assertEqual([row["lemma"] for row in self.db.next_unseen(source, 10)], ["猫"])
        excluded = {
            row["lemma"]: row["exclusion_reason"]
            for row in self.db.excluded_candidates([source])
        }
        self.assertEqual(excluded, {
            "う": "reaction_fragment", "なっ": "missing_definition",
        })

    def test_batch_and_existing_cards_never_share_an_example_sentence(self):
        source = self.add_show("Unique Examples", ["AB", "C"])
        rows = self.db.next_unseen(source, limit=3, metric="source")
        sentence_ids = [int(row["sentence_id"]) for row in rows]
        self.assertEqual(len(sentence_ids), len(set(sentence_ids)))
        self.assertEqual(len(rows), 2)

        reserved = rows[0]
        self.db.record_anki_card(
            int(reserved["lexeme_id"]), 900, 1900, source,
            int(reserved["sentence_id"]),
        )
        self.db.mark_known_by_id(int(reserved["lexeme_id"]))
        following = self.db.next_unseen(source, limit=3, metric="source")
        self.assertNotIn(
            int(reserved["sentence_id"]),
            {int(row["sentence_id"]) for row in following},
        )

    def test_reimport_releases_stale_sentence_reservation(self):
        source = self.add_show("Reserved Reimport", ["A"])
        row = self.db.next_unseen(source, limit=1)[0]
        self.db.record_anki_card(
            int(row["lexeme_id"]), 901, 1901, source, int(row["sentence_id"])
        )

        self.db.ingest_cues(
            source, [Cue(1, 0, 800, "A")], [], CharacterTokenizer()
        )

        reservation = self.db.connection.execute(
            "SELECT example_sentence_id FROM anki_cards WHERE note_id = 901"
        ).fetchone()[0]
        self.assertIsNone(reservation)

    def test_unreviewed_shared_card_moves_when_switching_sources(self):
        hxh = self.add_show("Hunter x Hunter", list("ABCDEFXY"))
        naruto = self.add_show("Naruto", list("CEFGH"))
        anki = FakeAnkiConnect()

        first = sync_source(self.db, [hxh], limit=6, metric="source", client=anki)
        self.assertEqual(first["added"], 6)
        anki.set_reps_for_expression(set("ABCDE"))

        switched = sync_source(self.db, [naruto], limit=3, metric="source", client=anki)
        self.assertEqual(switched, {
            "learned": 5, "added": 2, "moved_unreviewed": 1, "batch_size": 3,
        })
        f_card = next(
            card for card in anki.cards.values()
            if anki.notes[card["note_id"]]["fields"]["Expression"] == "F"
        )
        self.assertEqual(f_card["deck"], "Japanese Sources::Naruto")

        anki.set_reps_for_expression(set("FGH"))
        returned = sync_source(self.db, [hxh], limit=2, metric="source", client=anki)
        self.assertEqual(returned["added"], 2)
        remaining = {
            note["fields"]["Expression"] for note in anki.notes.values()
            if note["fields"]["Expression"] in {"X", "Y"}
        }
        self.assertEqual(remaining, {"X", "Y"})


if __name__ == "__main__":
    unittest.main()
