import unittest

from vocabdeck.progression import (
    desired_sentence_words,
    example_score,
    joint_planning_score,
)


class ProgressionTest(unittest.TestCase):
    def test_joint_planner_values_easy_context_more_at_start(self):
        common_with_unknown, early = joint_planning_score(15.0, 10.0, position=0)
        rarer_with_clear_context, _ = joint_planning_score(25.0, 0.0, position=0)
        self.assertLess(rarer_with_clear_context, common_with_unknown)
        self.assertEqual(early["context_weight"], 3.0)

    def test_joint_planner_relaxes_context_weight_later(self):
        common_with_unknown, later = joint_planning_score(15.0, 10.0, position=30)
        rarer_with_clear_context, _ = joint_planning_score(25.0, 0.0, position=30)
        self.assertLess(common_with_unknown, rarer_with_clear_context)
        self.assertEqual(later["context_weight"], 0.6)

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

    def test_easier_unknown_context_beats_harder_unknown_context(self):
        target_id = 10
        easier_context = {
            "word_ids": {target_id, 1},
            "japanese": "簡単な例。",
            "english": "An easy example.",
            "surface": "例",
            "lemma": "例",
        }
        harder_context = dict(easier_context, word_ids={target_id, 2})
        difficulties = {target_id: 20.0, 1: 10.0, 2: 50.0}

        easier_score, easier_details = example_score(
            easier_context, target_id, set(), 0, difficulties, 20.0
        )
        harder_score, harder_details = example_score(
            harder_context, target_id, set(), 0, difficulties, 20.0
        )

        self.assertLess(easier_score, harder_score)
        self.assertEqual(easier_details["harder_unknown_words"], 0)
        self.assertEqual(harder_details["harder_unknown_words"], 1)
        self.assertEqual(harder_details["harder_unknown_ids"], [2])
        self.assertEqual(harder_details["max_unknown_difficulty_gap"], 28.0)

    def test_small_difficulty_difference_is_tolerated(self):
        example = {
            "word_ids": {10, 1},
            "japanese": "短い例。",
            "english": "A short example.",
            "surface": "例",
            "lemma": "例",
        }

        _, details = example_score(example, 10, set(), 0, {1: 21.5}, 20.0)

        self.assertEqual(details["harder_unknown_words"], 0)
        self.assertEqual(details["unknown_difficulty_burden"], 0.0)

    def test_unrankable_unknown_context_is_conservatively_harder(self):
        example = {
            "word_ids": {10, 99},
            "japanese": "威張れることじゃねえよな。",
            "english": "That isn't something to brag about.",
            "surface": "ねえ",
            "lemma": "ない",
        }

        _, details = example_score(
            example, 10, set(), 0, {10: 16.3}, 16.3
        )

        self.assertEqual(details["harder_unknown_words"], 1)
        self.assertEqual(details["harder_unknown_ids"], [99])
        self.assertEqual(details["unscored_unknown_words"], 1)
        self.assertEqual(details["unscored_unknown_ids"], [99])

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

    def test_kana_iitai_is_not_used_as_an_example_for_good(self):
        false_good = {
            "word_ids": {10},
            "japanese": "何が いいたい？",
            "english": "What do you want to say?",
            "surface": "いい",
            "lemma": "いい",
            "target_end": 5,
        }
        real_good = dict(
            false_good,
            japanese="いいですね。",
            english="That's good.",
            target_end=2,
        )

        false_score, details = example_score(false_good, 10, set(), position=0)
        real_score, _ = example_score(real_good, 10, set(), position=0)
        self.assertGreater(false_score, real_score)
        self.assertTrue(details["sense_mismatch"])


if __name__ == "__main__":
    unittest.main()
