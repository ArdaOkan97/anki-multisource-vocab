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


if __name__ == "__main__":
    unittest.main()
