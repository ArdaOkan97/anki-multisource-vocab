import unittest

from vocabdeck.difficulty import difficulty_score, rank_candidates


def candidate(word, *, count=1, pos="動詞", words=3, unknown=3):
    return {
        "lexeme_key": word,
        "lemma": word,
        "part_of_speech": pos,
        "source_count": count,
        "sentence_word_count": words,
        "sentence_unknown_word_count": unknown,
        "japanese": f"{word}。",
        "english": "Example.",
        "cue_index": 1,
    }


class DifficultyTest(unittest.TestCase):
    def test_general_frequency_prefers_common_word(self):
        rows = rank_candidates([candidate("船長"), candidate("する")], "general")
        self.assertEqual(rows[0]["lemma"], "する")

    def test_source_frequency_can_prioritize_repeated_domain_word(self):
        rows = rank_candidates(
            [candidate("船長", count=25), candidate("する", count=1)], "source"
        )
        self.assertEqual(rows[0]["lemma"], "船長")

    def test_dialogue_filler_receives_noise_penalty(self):
        filler_score, filler = difficulty_score(candidate("あっ", pos="感動詞"), "hybrid")
        regular_score, regular = difficulty_score(candidate("なる"), "hybrid")
        self.assertEqual(filler["noise"], 1.0)
        self.assertGreater(filler_score, regular_score)


if __name__ == "__main__":
    unittest.main()
