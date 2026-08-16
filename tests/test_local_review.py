import json
import tempfile
import unittest
from pathlib import Path

from vocabdeck.cli import build_parser
from vocabdeck.local_review import (
    card_fingerprint,
    load_review_cards,
    load_review_records,
    parse_review_response,
    run_local_review,
)


class FakeReviewer:
    model_name = "fake-local"

    def __init__(self):
        self.calls = []

    def review(self, prompts):
        self.calls.append(list(prompts))
        responses = []
        for prompt in prompts:
            if "Target: そう" in prompt:
                responses.append(
                    '{"verdict":"incorrect","reason_code":"larger_expression"}'
                )
            else:
                responses.append(
                    '{"verdict":"correct","reason_code":"supported"}'
                )
        return responses, {
            "prompt_tokens": 100,
            "generation_tokens": 20,
            "prompt_time": 2.0,
            "generation_time": 1.0,
            "peak_memory": 7.5,
        }


class LocalReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.cards = [
            {
                "audit_position": 1,
                "lexeme_key": "sou",
                "lemma": "そう",
                "reading": "ソウ",
                "part_of_speech": "副詞",
                "gloss": "in that way; thus; such",
                "target_surface": "そう",
                "target_start": 0,
                "target_end": 2,
                "japanese": "そうか。",
                "english": "I see...",
                "gloss_score": 0.80,
                "example_progression": {"content_words": 1},
            },
            {
                "audit_position": 2,
                "lexeme_key": "neko",
                "lemma": "猫",
                "reading": "ネコ",
                "part_of_speech": "名詞",
                "gloss": "cat",
                "target_surface": "猫",
                "japanese": "猫だ。",
                "english": "It's a cat.",
                "gloss_score": 0.90,
                "example_progression": {"content_words": 1},
            },
            {
                "audit_position": 3,
                "lexeme_key": "inu",
                "lemma": "犬",
                "reading": "イヌ",
                "part_of_speech": "名詞",
                "gloss": "dog",
                "target_surface": "犬",
                "japanese": "犬が走る。",
                "english": "A dog runs.",
                "gloss_score": 0.90,
                "example_progression": {"content_words": 2},
            },
        ]
        (self.directory / "audit.json").write_text(
            json.dumps({"cards": self.cards}, ensure_ascii=False),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_parses_only_supported_structured_responses(self):
        self.assertEqual(
            parse_review_response(
                '```json\n{"verdict":"correct","reason_code":"supported"}\n```'
            ),
            {"verdict": "correct", "reason_code": "supported"},
        )
        with self.assertRaisesRegex(ValueError, "correct verdict"):
            parse_review_response(
                '{"verdict":"correct","reason_code":"wrong_sense"}'
            )
        self.assertEqual(
            parse_review_response(
                '{"verdict":"incorrect","reason_code":"wrong_sense",'
                '"reason":"truncated explanation'
            ),
            {"verdict": "incorrect", "reason_code": "wrong_sense"},
        )

    def test_minimal_filter_and_resumable_jsonl_output(self):
        selected = load_review_cards(
            self.directory / "audit.json", minimal_only=True
        )
        self.assertEqual([card["audit_position"] for card in selected], [1, 2])
        output = self.directory / "reviews.jsonl"
        first = FakeReviewer()
        summary = run_local_review(
            selected, output, first, batch_size=1, limit=1
        )
        self.assertEqual(summary["reviewed_now"], 1)
        second = FakeReviewer()
        resumed = run_local_review(selected, output, second, batch_size=4)
        self.assertEqual(resumed["previously_reviewed"], 1)
        self.assertEqual(resumed["reviewed_now"], 1)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual([row["audit_position"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["reason_code"], "larger_expression")
        self.assertEqual(rows[0]["card_fingerprint"], card_fingerprint(selected[0]))
        self.assertIn("Japanese sentence (target marked with ⟦ ⟧): ⟦そう⟧か。", first.calls[0][0])
        self.assertEqual(
            [row["audit_position"] for row in load_review_records(output)],
            [1, 2],
        )

    def test_cli_accepts_local_review_options(self):
        args = build_parser().parse_args([
            "review-calibration-local",
            "--input", "audit.json",
            "--output", "reviews.jsonl",
            "--minimal-only",
            "--batch-size", "4",
            "--limit", "8",
            "--review-pass", "recoverability",
            "--deterministic-clean-only",
            "--max-per-target", "2",
            "--thinking",
        ])
        self.assertEqual(args.batch_size, 4)
        self.assertTrue(args.minimal_only)
        self.assertEqual(args.limit, 8)
        self.assertEqual(args.review_pass, "recoverability")
        self.assertTrue(args.deterministic_clean_only)
        self.assertEqual(args.max_per_target, 2)
        self.assertTrue(args.thinking)

        validation = build_parser().parse_args([
            "validate-reviewed-cards",
            "--input", "audit.json",
            "--contextual-reviews", "context.jsonl",
            "--recoverability-reviews", "recoverability.jsonl",
            "--contextual-gloss-reviews", "gloss.jsonl",
            "--output", "validation.json",
            "--minimal-only",
        ])
        self.assertEqual(validation.command, "validate-reviewed-cards")
        self.assertTrue(validation.minimal_only)

        candidates = build_parser().parse_args([
            "plan-validation-candidates",
            "--series", "Show", "--season", "1", "--episodes", "1-10",
            "--targets", "200", "--candidates-per-target", "5",
            "--output", "candidates.json",
        ])
        self.assertEqual(candidates.targets, 200)
        self.assertEqual(candidates.candidates_per_target, 5)

        frontier = build_parser().parse_args([
            "plan-review-frontier",
            "--input", "candidates.json",
            "--selection", "selection.json",
            "--limit", "20",
            "--output", "frontier.json",
        ])
        self.assertEqual(frontier.command, "plan-review-frontier")
        self.assertEqual(frontier.limit, 20)


if __name__ == "__main__":
    unittest.main()
