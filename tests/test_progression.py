import unittest

from vocabdeck.progression import desired_sentence_words, example_score


class ProgressionTest(unittest.TestCase):
    def test_desired_sentence_length_grows_gradually(self):
        self.assertEqual(desired_sentence_words(0), 2)
        self.assertEqual(desired_sentence_words(5), 3)
        self.assertEqual(desired_sentence_words(30), 8)
        self.assertEqual(desired_sentence_words(100), 8)

    def test_known_context_beats_shorter_unknown_context(self):
        target_id = 10
        known_context = {
            "word_ids": {target_id, 1, 2, 3},
            "japanese": "これは良い例です。",
            "english": "This is a good example.",
            "surface": "例",
            "lemma": "例",
        }
        unknown_context = {
            "word_ids": {target_id, 99},
            "japanese": "難しい例。",
            "english": "A difficult example.",
            "surface": "例",
            "lemma": "例",
        }

        known_score, known_details = example_score(
            known_context, target_id, {1, 2, 3}, position=10
        )
        unknown_score, unknown_details = example_score(
            unknown_context, target_id, {1, 2, 3}, position=10
        )

        self.assertLess(known_score, unknown_score)
        self.assertEqual(known_details["unknown_other_words"], 0)
        self.assertEqual(unknown_details["unknown_other_words"], 1)

    def test_missing_translation_is_strongly_penalized(self):
        translated = {
            "word_ids": {10, 1},
            "japanese": "良い例。",
            "english": "A good example.",
            "surface": "例",
            "lemma": "例",
        }
        untranslated = dict(translated, english="")

        translated_score, _ = example_score(translated, 10, {1}, position=0)
        untranslated_score, details = example_score(untranslated, 10, {1}, position=0)

        self.assertLess(translated_score, untranslated_score)
        self.assertTrue(details["missing_translation"])

    def test_multiple_utterances_are_penalized(self):
        clean = {
            "word_ids": {10, 1},
            "japanese": "猫がいる。",
            "english": "There is a cat.",
            "surface": "猫",
            "lemma": "猫",
        }
        mixed = dict(clean, japanese="猫がいる。 何？")

        clean_score, _ = example_score(clean, 10, {1}, position=0)
        mixed_score, details = example_score(mixed, 10, {1}, position=0)

        self.assertLess(clean_score, mixed_score)
        self.assertTrue(details["multi_utterance"])


if __name__ == "__main__":
    unittest.main()
