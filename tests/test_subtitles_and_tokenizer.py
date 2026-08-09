import unittest

from vocabdeck.subtitles import align_translation, merge_continuations, parse_srt_text
from vocabdeck.tokenizer import JapaneseTokenizer


class SubtitleAndTokenizerTest(unittest.TestCase):
    def test_parses_and_aligns_srt_by_overlap(self):
        japanese = parse_srt_text(
            "1\n00:00:01,000 --> 00:00:02,000\n私は猫が好きです。\n"
        )
        english = parse_srt_text(
            "1\n00:00:00,900 --> 00:00:02,100\nI like cats.\n"
        )
        self.assertEqual(japanese[0].start_ms, 1000)
        self.assertEqual(align_translation(japanese[0], english), "I like cats.")

    def test_alignment_keeps_split_translation_fragments(self):
        japanese = parse_srt_text(
            "1\n00:00:03,980 --> 00:00:05,500\nハンターって。\n"
        )[0]
        english = parse_srt_text(
            "1\n00:00:01,000 --> 00:00:04,000\nBeing a Hunter is so great,\n\n"
            "2\n00:00:04,030 --> 00:00:05,400\nhe abandoned his own kid!\n"
        )
        self.assertEqual(
            align_translation(japanese, english),
            "Being a Hunter is so great, he abandoned his own kid!",
        )

    def test_merges_japanese_arrow_continuations(self):
        cues = parse_srt_text(
            "1\n00:00:01,000 --> 00:00:02,000\n世界一になって→\n\n"
            "2\n00:00:02,100 --> 00:00:03,000\n帰って来る。\n"
        )
        merged = merge_continuations(cues)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "世界一になって 帰って来る。")
        self.assertEqual((merged[0].start_ms, merged[0].end_ms), (1000, 3000))

    def test_unidic_produces_dictionary_forms(self):
        tokens = JapaneseTokenizer().tokenize("猫が走った。")
        by_surface = {token.surface: token for token in tokens}
        self.assertEqual(by_surface["猫"].lemma, "猫")
        self.assertEqual(by_surface["走っ"].lemma, "走る")

    def test_uses_reading_base_and_excludes_proper_names(self):
        tokens = JapaneseTokenizer().tokenize("努力をしなさい。レオが来た。")
        by_surface = {token.surface: token for token in tokens}
        self.assertEqual((by_surface["し"].lemma, by_surface["し"].reading), ("する", "スル"))
        self.assertNotIn("レオ", by_surface)


if __name__ == "__main__":
    unittest.main()
