import tempfile
import unittest
from pathlib import Path

from vocabdeck.audit import audit_queue, render_audit_html, select_clean_cards
from vocabdeck.cli import build_parser
from vocabdeck.readings import ReadingConsensus


class FakeEmbedder:
    model_name = "fake"

    def similarity(self, query, passage):
        if query == "猫が来た。":
            return 0.61
        if query == "A dog arrived.":
            return 0.52
        raise AssertionError((query, passage))


class FakeReadingValidator:
    def validate(self, text, start, end, expected):
        return ReadingConsensus(
            "agreement", expected, expected, expected,
            ("sudachi-test", "openjtalk"),
        )


class DisagreeingReadingValidator:
    def validate(self, text, start, end, expected):
        return ReadingConsensus(
            "disagreement", expected, "ビョウ", "ビョウ",
            ("sudachi-test", "openjtalk"),
        )


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
                "target_lexical_start": 0,
                "target_lexical_end": 1,
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
                "target_lexical_start": 0,
                "target_lexical_end": 1,
                "example_progression": {},
            },
        ]

    def lexeme_labels(self, lexeme_ids):
        return ["到着（トウチャク）"] if lexeme_ids else []

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
    def test_clean_selection_rechecks_context_after_dropping_word(self):
        class SelectionDatabase:
            def sentence_lexeme_ids(self, sentence_id):
                return {1} if sentence_id == 10 else {1, 2}

        report = {"cards": [
            {
                "audit_position": 1, "lexeme_id": 1, "lexeme_key": "難|ナン",
                "lemma": "難", "reading": "ナン", "sentence_id": 10,
                "japanese": "難", "english": "hard", "difficulty_score": 20.0,
                "audit_findings": [{"code": "weak_subtitle_alignment"}],
                "example_progression": {},
            },
            {
                "audit_position": 2, "lexeme_id": 2, "lexeme_key": "易|イ",
                "lemma": "易", "reading": "イ", "sentence_id": 20,
                "japanese": "難易", "english": "difficulty", "difficulty_score": 10.0,
                "audit_findings": [], "example_progression": {},
            },
        ]}
        selection = select_clean_cards(SelectionDatabase(), report, 1)
        self.assertFalse(selection["summary"]["complete"])
        self.assertEqual(
            selection["rejected"][1]["reasons"],
            ["rejected_word_became_harder_context"],
        )

    def test_clean_selection_restores_easier_unknown_without_rejecting(self):
        class SelectionDatabase:
            def sentence_lexeme_ids(self, sentence_id):
                return {1} if sentence_id == 10 else {1, 2}

        report = {"cards": [
            {
                "audit_position": 1, "lexeme_id": 1, "lexeme_key": "易|イ",
                "lemma": "易", "reading": "イ", "sentence_id": 10,
                "japanese": "易", "english": "easy", "difficulty_score": 10.0,
                "audit_findings": [{"code": "ambiguous_expression"}],
                "example_progression": {},
            },
            {
                "audit_position": 2, "lexeme_id": 2, "lexeme_key": "難|ナン",
                "lemma": "難", "reading": "ナン", "sentence_id": 20,
                "japanese": "難易", "english": "difficulty", "difficulty_score": 20.0,
                "audit_findings": [], "example_progression": {},
            },
        ]}
        selection = select_clean_cards(SelectionDatabase(), report, 1)
        self.assertTrue(selection["summary"]["complete"])
        self.assertEqual(
            selection["accepted"][0]["example_progression"]["unknown_other_ids"],
            [1],
        )

    def test_flags_actionable_quality_risks(self):
        report = audit_queue(
            FakeDatabase(), [1], limit=2, embedder=FakeEmbedder(),
            reading_validator=FakeReadingValidator(),
        )
        first_codes = {
            item["code"] for item in report["cards"][0]["audit_findings"]
        }
        self.assertEqual(first_codes, {
            "weak_subtitle_alignment",
            "weak_gloss_support",
            "harder_unknown_context",
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
            "high": 4, "medium": 2, "info": 0,
        })
        self.assertEqual(
            report["summary"]["criterion_counts"]["translation_available"],
            {"passed": 1, "flagged": 1, "not_checked": 0},
        )
        first_criteria = {
            item["code"]: item["status"]
            for item in report["cards"][0]["audit_criteria"]
        }
        self.assertEqual(first_criteria, {
            "translation_available": "passed",
            "translation_alignment": "flagged",
            "definition_available": "passed",
            "gloss_support": "flagged",
            "context_difficulty": "flagged",
            "contextual_reading": "passed",
            "expression_interpretation": "flagged",
            "unique_example": "passed",
        })
        second_criteria = {
            item["code"]: item["status"]
            for item in report["cards"][1]["audit_criteria"]
        }
        self.assertEqual(second_criteria, {
            "translation_available": "flagged",
            "translation_alignment": "not_checked",
            "definition_available": "flagged",
            "gloss_support": "not_checked",
            "context_difficulty": "passed",
            "contextual_reading": "passed",
            "expression_interpretation": "passed",
            "unique_example": "passed",
        })

    def test_renders_filterable_standalone_report(self):
        report = audit_queue(
            FakeDatabase(), [1], limit=2, embedder=FakeEmbedder(),
            reading_validator=FakeReadingValidator(),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.html"
            render_audit_html(report, output)
            document = output.read_text(encoding="utf-8")
        self.assertIn("Vocabulary quality audit", document)
        self.assertIn("Translation alignment", document)
        self.assertIn("Reliable definition available", document)
        self.assertIn("PASS", document)
        self.assertIn("FLAG", document)
        self.assertIn("N/A", document)
        self.assertIn("猫", document)
        self.assertIn('data-filter="flagged"', document)
        self.assertIn("Excluded candidates", document)
        self.assertIn("Not eligible for Anki", document)
        self.assertIn("UniDic ネコ · Sudachi ネコ · OpenJTalk ネコ", document)

    def test_flags_only_evidence_backed_reading_disagreement(self):
        report = audit_queue(
            FakeDatabase(), [1], limit=1, embedder=FakeEmbedder(),
            reading_validator=DisagreeingReadingValidator(),
        )
        finding = next(
            item for item in report["cards"][0]["audit_findings"]
            if item["code"] == "reading_disagreement"
        )
        self.assertEqual(finding["severity"], "high")
        self.assertIn("Sudachi ビョウ", finding["explanation"])

    def test_cli_accepts_episode_range(self):
        args = build_parser().parse_args([
            "audit", "--series", "Show", "--season", "1",
            "--episodes", "1-3", "--output", "audit.html",
        ])
        self.assertEqual(args.episodes, [1, 2, 3])
        self.assertEqual(args.limit, 100)


if __name__ == "__main__":
    unittest.main()
