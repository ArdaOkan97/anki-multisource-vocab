import tempfile
import unittest
from pathlib import Path

from vocabdeck.database import VocabularyDatabase
from vocabdeck.anki import sync_source
from vocabdeck.subtitles import Cue
from vocabdeck.tokenizer import LexemeToken


class CharacterTokenizer:
    def tokenize(self, text):
        return [LexemeToken(char, char, char, "名詞") for char in text.replace(" ", "")]


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
