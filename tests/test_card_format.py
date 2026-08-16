import unittest

from vocabdeck.anki import BACK, FRONT
from vocabdeck.card_format import (
    blank_target, highlight_target, hiragana, learner_pos, learner_target_span,
    learner_target_spans,
)


class CardFormatTest(unittest.TestCase):
    def test_learner_span_excludes_attached_polite_copula(self):
        target, start, end = learner_target_span({
            "japanese": "いいですね？",
            "lemma": "いい",
            "target_surface": "いいです",
            "target_start": 0,
            "target_end": 4,
            "target_lexical_start": 0,
            "target_lexical_end": 2,
        })
        self.assertEqual((target, start, end), ("いい", 0, 2))
        self.assertEqual(
            blank_target("いいですね？", target, start, end),
            '<span class="target-blank">（　）</span>ですね？',
        )

    def test_blanks_only_first_target_and_escapes_input(self):
        result = blank_target("猫と猫 < 3", "猫")
        self.assertEqual(
            result,
            '<span class="target-blank">（　）</span>と猫 &lt; 3',
        )

    def test_blanks_every_analyzed_occurrence_of_same_lexeme(self):
        row = {
            "japanese": "いいねぇ いいよ～。",
            "lemma": "いい",
            "target_lexical_start": 0,
            "target_lexical_end": 2,
            "target_lexical_spans": [[0, 2], [5, 7]],
        }
        target, start, end = learner_target_span(row)
        spans = learner_target_spans(row)
        self.assertEqual(
            blank_target(row["japanese"], target, start, end, spans),
            '<span class="target-blank">（　）</span>ねぇ '
            '<span class="target-blank">（　）</span>よ～。',
        )
        self.assertEqual(
            highlight_target(row["japanese"], target, start, end, spans).count(
                'class="target-answer"'
            ),
            2,
        )

    def test_highlights_answer_and_converts_reading(self):
        self.assertIn("target-answer", highlight_target("猫がいる。", "猫"))
        self.assertEqual(hiragana("ネコ"), "ねこ")
        self.assertEqual(learner_pos("名詞"), "Noun")
        self.assertEqual(learner_pos("代名詞"), "Pronoun")
        self.assertEqual(learner_pos("表現"), "Expression")

    def test_exact_span_avoids_same_text_in_another_word(self):
        sentence = "おい 誰か いねえか～？"
        result = blank_target(sentence, "い", 6, 7)
        self.assertIn("おい 誰か", result)
        self.assertIn('誰か <span class="target-blank">（　）</span>ねえ', result)

    def test_anki_front_does_not_contain_expression_or_full_sentence(self):
        self.assertNotIn("{{Expression}}", FRONT)
        self.assertNotIn("{{Sentence}}", FRONT)
        self.assertIn("{{SentenceCloze}}", FRONT)
        self.assertIn("{{Expression}}", BACK)
        self.assertIn("{{SentenceAnswer}}", BACK)


if __name__ == "__main__":
    unittest.main()
