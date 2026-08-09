import unittest

from vocabdeck.dictionary import JMDictResolver


class DictionaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = JMDictResolver()

    def test_selects_basic_suru_sense_over_incidental_context_word(self):
        match = self.resolver.resolve("する", "スル", "動詞", "I will pass the exam")
        self.assertIsNotNone(match)
        self.assertEqual(match.entry_id, 1157170)
        self.assertIn("to do", match.gloss)

    def test_selects_iru_exist_entry_instead_of_homophone(self):
        match = self.resolver.resolve("いる", "イル", "動詞", "He was there")
        self.assertIsNotNone(match)
        self.assertEqual(match.entry_id, 1577980)
        self.assertIn("to exist", match.gloss)

    def test_nai_gloss_covers_negative_and_lexical_uses(self):
        match = self.resolver.resolve("ない", "ナイ", "形容詞", "There is no choice")
        self.assertIsNotNone(match)
        self.assertEqual(match.entry_id, 1529520)
        self.assertIn("not", match.gloss)
        self.assertIn("nonexistent", match.gloss)

    def test_iu_selects_speaking_instead_of_arranging_hair(self):
        match = self.resolver.resolve("いう", "イウ", "動詞", "What did you say?")
        self.assertIsNotNone(match)
        self.assertEqual(match.entry_id, 1587040)
        self.assertIn("to say", match.gloss)


if __name__ == "__main__":
    unittest.main()
