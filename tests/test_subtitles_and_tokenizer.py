import unittest

from vocabdeck.dictionary import JMDictResolver
from vocabdeck.semantics import ExpressionDecision
from vocabdeck.subtitles import align_translation, merge_continuations, parse_srt_text
from vocabdeck.tokenizer import JapaneseTokenizer


class FixedExpressionScorer:
    def __init__(self, decision="expression"):
        self.decision = decision

    def decide(
        self, english, phrase_senses, component_glosses, standalone=False,
        particle_inclusive=False,
    ):
        return ExpressionDecision(
            decision=self.decision,
            phrase_score=0.95,
            component_score=0.20,
            margin=0.75,
            opacity=0.80,
            phrase_description=phrase_senses[0],
            component_description=" | ".join(component_glosses),
            model="test-embedder",
        )


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

    def test_alignment_drops_weak_previous_boundary_overlap(self):
        japanese = parse_srt_text(
            "1\n00:00:03,000 --> 00:00:05,000\n何だよ それ。\n"
        )[0]
        english = parse_srt_text(
            "1\n00:00:01,500 --> 00:00:03,200\nThen you buy me dinner!\n\n"
            "2\n00:00:03,200 --> 00:00:04,900\nI don't get it.\n"
        )
        self.assertEqual(align_translation(japanese, english), "I don't get it.")

    def test_alignment_keeps_multiple_fully_covered_sentences(self):
        japanese = parse_srt_text(
            "1\n00:00:01,000 --> 00:00:06,000\n長い日本語の字幕。\n"
        )[0]
        english = parse_srt_text(
            "1\n00:00:01,200 --> 00:00:02,500\nFirst sentence.\n\n"
            "2\n00:00:02,600 --> 00:00:04,200\nSecond sentence.\n\n"
            "3\n00:00:05,900 --> 00:00:07,500\nFollowing dialogue.\n"
        )
        self.assertEqual(
            align_translation(japanese, english), "First sentence. Second sentence."
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

    def test_potential_verb_falls_back_to_dictionary_lemma(self):
        text = "威張れることじゃねえよな。"
        tokenizer = JapaneseTokenizer()
        target = next(
            token for token in tokenizer.tokenize(text)
            if token.surface == "威張れる"
        )

        self.assertEqual((target.lemma, target.reading), ("威張る", "イバル"))
        self.assertEqual(text[target.start:target.end], "威張れる")
        self.assertEqual(
            tokenizer.find_inflected_span(
                text, "威張る", "イバル", "威張れる"
            ),
            (0, 4),
        )
        match = JMDictResolver().resolve(
            target.lemma, target.reading, target.part_of_speech,
            "That isn't something to brag about.",
        )
        self.assertIsNotNone(match)
        self.assertIn("to put on airs", match.gloss)

    def test_tracks_exact_span_for_inflected_iru_after_unrelated_i(self):
        text = "おい 誰か いねえか～？"
        tokenizer = JapaneseTokenizer()
        tokens = tokenizer.tokenize(text)
        target = next(token for token in tokens if token.lemma == "いる")
        self.assertEqual(target.surface, "い")
        self.assertEqual(text[target.start:target.end], "い")
        self.assertEqual(target.start, 6)
        span = tokenizer.find_inflected_span(text, "いる", "イル", "い")
        self.assertEqual(span, (6, 9))
        self.assertEqual(text[span[0]:span[1]], "いねえ")

    def test_inflected_span_includes_past_auxiliary(self):
        text = "去年もいたのか？"
        tokenizer = JapaneseTokenizer()
        span = tokenizer.find_inflected_span(text, "いる", "イル", "い")
        self.assertEqual(text[span[0]:span[1]], "いた")

    def test_pronouns_are_teachable_content_words(self):
        tokens = JapaneseTokenizer().tokenize("何？")
        by_surface = {token.surface: token for token in tokens}
        self.assertEqual(by_surface["何"].lemma, "何")
        self.assertEqual(by_surface["何"].reading, "ナニ")
        self.assertEqual(by_surface["何"].part_of_speech, "代名詞")

    def test_noun_like_suffixes_are_tracked_as_sentence_context(self):
        tokenizer = JapaneseTokenizer()
        armored = tokenizer.tokenize("装甲車？")
        plural = tokenizer.tokenize("俺達？")
        self.assertEqual(
            [(token.surface, token.part_of_speech) for token in armored],
            [("装甲", "名詞"), ("車", "接尾辞")],
        )
        self.assertEqual(
            [(token.surface, token.part_of_speech) for token in plural],
            [("俺", "代名詞"), ("達", "接尾辞")],
        )

    def test_nani_reading_before_common_particles(self):
        tokenizer = JapaneseTokenizer()
        for text in ("何が？", "何を？", "何に？"):
            target = next(
                token for token in tokenizer.tokenize(text) if token.lemma == "何"
            )
            self.assertEqual(target.reading, "ナニ")

    def test_dictionary_expression_suppresses_component_occurrences(self):
        result = JapaneseTokenizer(
            expression_scorer=FixedExpressionScorer()
        ).tokenize_with_context("どうも。", "Thank you.")
        tokens = result.tokens
        self.assertEqual(
            [(token.surface, token.lemma, token.part_of_speech) for token in tokens],
            [("どうも", "どうも", "表現")],
        )

    def test_compositional_words_remain_separate(self):
        tokens = JapaneseTokenizer().tokenize("どうする？")
        self.assertEqual(
            [(token.lemma, token.part_of_speech) for token in tokens],
            [("どう", "副詞"), ("する", "動詞")],
        )

    def test_contextual_homograph_is_not_recombined_as_expression(self):
        result = JapaneseTokenizer(
            expression_scorer=FixedExpressionScorer()
        ).tokenize_with_context("私もします。", "I will do it too.")
        self.assertNotIn("もし", {token.lemma for token in result.tokens})
        self.assertEqual(result.expression_analyses, [])

    def test_expression_target_span_covers_complete_phrase(self):
        tokenizer = JapaneseTokenizer()
        span = tokenizer.find_inflected_span("どうも。", "どうも", "ドウモ", "どうも")
        self.assertEqual(span, (0, 3))

    def test_expression_uses_contextual_surface_reading(self):
        result = JapaneseTokenizer(
            expression_scorer=FixedExpressionScorer()
        ).tokenize_with_context("何のこと？", "What do you mean?")
        target = result.tokens[0]
        self.assertEqual((target.lemma, target.reading), ("何の", "ナンノ"))

    def test_particle_inclusive_expression_suppresses_component(self):
        result = JapaneseTokenizer(
            expression_scorer=FixedExpressionScorer("expression")
        ).tokenize_with_context("何で？", "Why?")
        self.assertEqual(
            [(token.lemma, token.reading, token.part_of_speech)
             for token in result.tokens],
            [("何で", "ナンデ", "表現")],
        )
        self.assertEqual(result.expression_analyses[0].surface, "何で")

    def test_rejected_particle_expression_keeps_content_component(self):
        result = JapaneseTokenizer(
            expression_scorer=FixedExpressionScorer("components")
        ).tokenize_with_context("何で書く？", "What will you write with?")
        self.assertEqual(
            [(token.lemma, token.reading) for token in result.tokens],
            [("何", "ナン"), ("書く", "カク")],
        )
        self.assertEqual(result.expression_analyses[0].decision, "components")

    def test_kana_iitai_is_canonicalized_as_iu(self):
        tokens = JapaneseTokenizer().tokenize("何が いいたい？")
        by_surface = {token.surface: token for token in tokens}
        self.assertEqual(by_surface["いい"].lemma, "いう")
        self.assertEqual(by_surface["いい"].reading, "イウ")
        self.assertEqual(by_surface["いい"].part_of_speech, "動詞")


if __name__ == "__main__":
    unittest.main()
