import tempfile
import unittest
from pathlib import Path

from vocabdeck.audit import audit_queue, render_audit_html
from vocabdeck.cli import build_parser


class FakeEmbedder:
    model_name = "fake"

    def similarity(self, query, passage):
        if query == "猫が来た。":
            return 0.61
        if query == "A dog arrived.":
            return 0.52
        raise AssertionError((query, passage))


class FakeDatabase:
    def next_unseen_for_sources(self, source_ids, limit, metric):
        return [
            {
                "sentence_id": 11,
                "lexeme_key": "猫|ネコ",
                "lemma": "猫",
                "reading": "ネコ",
                "part_of_speech": "名詞",
                "gloss": "cat",
                "japanese": "猫が来た。",
                "english": "A dog arrived.",
                "difficulty_score": 12.0,
                "series": "Test Show",
                "season": 1,
                "episode": 2,
                "target_start": 0,
                "target_end": 1,
                "example_progression": {
                    "harder_unknown_words": 1,
                    "harder_unknown_ids": [9],
                },
            },
            {
                "sentence_id": 12,
                "lexeme_key": "犬|イヌ",
                "lemma": "犬",
                "reading": "イヌ",
                "part_of_speech": "名詞",
                "gloss": None,
                "japanese": "犬。",
                "english": None,
                "difficulty_score": 16.0,
                "series": "Test Show",
                "season": 1,
                "episode": 2,
                "target_start": 0,
                "target_end": 1,
                "example_progression": {},
            },
        ]

    def lexeme_labels(self, lexeme_ids):
        return ["到着（トウチャク）"] if lexeme_ids else []

    def reading_variants(self, lemma, reading):
        return ["猫（ビョウ）"] if lemma == "猫" else []

    def expression_analyses_for_sentence(self, sentence_id):
        if sentence_id != 11:
            return []
        return [{
            "start_char": 0,
            "end_char": 2,
            "surface": "猫が",
            "decision": "ambiguous",
            "margin": 0.01,
            "opacity": 0.4,
        }]

    def excluded_candidates(self, source_ids, limit=100):
        return [{
            "lexeme_key": "なっ|ナッ",
            "lemma": "なっ",
            "reading": "ナッ",
            "series": "Test Show",
            "season": 1,
            "episode": 2,
            "japanese": "なっ 何だ？",
            "english": "What?",
            "exclusion_reason": "missing_definition",
        }]


class AuditTest(unittest.TestCase):
    def test_flags_actionable_quality_risks(self):
        report = audit_queue(
            FakeDatabase(), [1], limit=2, embedder=FakeEmbedder()
        )
        first_codes = {
            item["code"] for item in report["cards"][0]["audit_findings"]
        }
        self.assertEqual(first_codes, {
            "weak_subtitle_alignment",
            "weak_gloss_support",
            "harder_unknown_context",
            "alternate_reading",
            "ambiguous_expression",
        })
        second_codes = {
            item["code"] for item in report["cards"][1]["audit_findings"]
        }
        self.assertEqual(second_codes, {
            "missing_translation", "missing_definition",
        })
        self.assertEqual(report["summary"]["cards_with_findings"], 2)
        self.assertEqual(report["summary"]["excluded_candidates"], 1)
        self.assertEqual(report["summary"]["severity_counts"], {
            "high": 4, "medium": 2, "info": 1,
        })

    def test_renders_filterable_standalone_report(self):
        report = audit_queue(
            FakeDatabase(), [1], limit=2, embedder=FakeEmbedder()
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.html"
            render_audit_html(report, output)
            document = output.read_text(encoding="utf-8")
        self.assertIn("Vocabulary quality audit", document)
        self.assertIn("Translation deserves review", document)
        self.assertIn("猫", document)
        self.assertIn('data-filter="flagged"', document)
        self.assertIn("Excluded candidates", document)
        self.assertIn("Not eligible for Anki", document)

    def test_cli_accepts_episode_range(self):
        args = build_parser().parse_args([
            "audit", "--series", "Show", "--season", "1",
            "--episodes", "1-3", "--output", "audit.html",
        ])
        self.assertEqual(args.episodes, [1, 2, 3])
        self.assertEqual(args.limit, 100)


if __name__ == "__main__":
    unittest.main()
