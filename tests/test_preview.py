import tempfile
import unittest
from pathlib import Path

from vocabdeck.preview import render_preview_html


class PreviewTest(unittest.TestCase):
    def test_renders_revealable_card_without_media(self):
        row = {
            "lexeme_key": "猫|ネコ|名詞",
            "lemma": "猫",
            "reading": "ネコ",
            "gloss": "cat",
            "japanese": "猫がいる。",
            "english": "There is a cat.",
            "target_surface": "猫",
            "difficulty_score": 12.5,
            "series": "Test Show",
            "season": 1,
            "episode": 2,
            "video_path": "",
            "start_ms": 1000,
            "end_ms": 2000,
            "example_progression": {
                "content_words": 2,
                "unknown_other_words": 1,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.html"
            rendered = render_preview_html([row], output, include_media=False)
            document = rendered.read_text(encoding="utf-8")

        self.assertIn('<span class="target-blank">（　）</span>がいる。', document)
        self.assertIn('<section class="answer" hidden>', document)
        self.assertIn("Show answer", document)
        self.assertIn('<span class="target-answer">猫</span>がいる。', document)
        self.assertIn("cat", document)
        self.assertIn("Test Show S01E02", document)
        self.assertIn("2 content words", document)
        self.assertIn("1 other unknown word (excluding the target)", document)
        row["scheduling"] = {"unknown_context_words": 0}
        with tempfile.TemporaryDirectory() as directory:
            scheduled = render_preview_html(
                [row], Path(directory) / "scheduled.html", include_media=False,
            ).read_text(encoding="utf-8")
        self.assertIn("0 other unknown words (excluding the target)", scheduled)
        self.assertNotIn("1 other unknown word", scheduled)

    def test_cloze_keeps_grammar_outside_lexical_blank(self):
        row = {
            "lexeme_key": "いい|イイ", "lemma": "いい", "reading": "イイ",
            "part_of_speech": "形容詞", "gloss": "good",
            "japanese": "いいですね？", "english": "Are we clear?",
            "target_surface": "いいです", "target_start": 0, "target_end": 4,
            "target_lexical_start": 0, "target_lexical_end": 2,
            "difficulty_score": 10, "series": "Test", "season": 1,
            "episode": 1, "video_path": "", "start_ms": 0, "end_ms": 1000,
            "example_progression": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.html"
            document = render_preview_html(
                [row], output, include_media=False
            ).read_text(encoding="utf-8")
        self.assertIn(
            '<span class="target-blank">（　）</span>ですね？', document
        )
        self.assertIn(
            '<span class="target-answer">いい</span>ですね？', document
        )

    def test_repeated_target_is_not_revealed_on_front(self):
        row = {
            "lexeme_key": "いい|イイ", "lemma": "いい", "reading": "イイ",
            "part_of_speech": "形容詞", "gloss": "good",
            "japanese": "いいねぇ いいよ～。", "english": "Very nice.",
            "target_surface": "いい", "target_start": 0, "target_end": 2,
            "target_lexical_start": 0, "target_lexical_end": 2,
            "target_lexical_spans": [[0, 2], [5, 7]],
            "difficulty_score": 10, "series": "Test", "season": 1,
            "episode": 1, "video_path": "", "start_ms": 0, "end_ms": 1000,
            "example_progression": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.html"
            document = render_preview_html(
                [row], output, include_media=False
            ).read_text(encoding="utf-8")
        self.assertIn(
            '<span class="target-blank">（　）</span>ねぇ '
            '<span class="target-blank">（　）</span>よ～。',
            document,
        )


if __name__ == "__main__":
    unittest.main()
