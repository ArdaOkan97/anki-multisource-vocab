import json
import tempfile
import unittest
from pathlib import Path

from vocabdeck.gold_benchmark import (
    build_gold_dataset,
    evaluate_predictions,
    render_blinded_html,
    validate_dataset,
)


def _card(position, *, series="Hunter x Hunter", episode=1):
    return {
        "position": position,
        "audit_position": position,
        "candidate_key": f"candidate-{series}-{position}",
        "learning_unit_key": f"word::jmdict:{position}:0",
        "sense_key": f"jmdict:{position}:0",
        "lemma": f"語{position}",
        "reading": "ゴ",
        "part_of_speech": "名詞",
        "gloss": f"meaning {position}",
        "target_surface": f"語{position}",
        "japanese": f"例文{position}",
        "english": f"Example {position}",
        "series": series,
        "season": 1,
        "episode": episode,
        "cue_index": position,
    }


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class GoldBenchmarkTest(unittest.TestCase):
    def _dataset(self, directory):
        root = Path(directory)
        baseline = root / "baseline.json"
        review = root / "review.json"
        heldout = root / "heldout.json"
        second = root / "second.json"
        _write(baseline, [_card(index) for index in range(1, 101)])
        _write(review, {
            "baseline_id": "test-baseline",
            "reviewed_range": {"start": 1, "end": 100},
            "flagged_cards": [
                {"position": 40, "categories": ["near_duplicate_learning_unit"], "user_note": "duplicate"},
                {"position": 56, "categories": ["audio_quality"], "user_note": "audio"},
                {"position": 68, "categories": ["subtitle_contamination"], "user_note": "subtitle"},
                {"position": 69, "categories": ["unknown_context_under_count"], "user_note": "unknown"},
                {"position": 78, "categories": ["wrong_contextual_sense", "semantic_duplicate"], "user_note": "sense"},
            ],
        })
        _write(heldout, {"cards": [_card(index, episode=11) for index in range(101, 111)]})
        _write(second, {"cards": [_card(index, series="Second Show") for index in range(201, 211)]})
        return build_gold_dataset(baseline, review, heldout, second, queue_size=5)

    def test_dataset_validation_and_human_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._dataset(directory)
        validate_dataset(dataset)
        development = dataset["splits"]["development"]
        self.assertEqual(len(development), 100)
        decisions = {
            row["card"]["audit_position"]: row["labels"]["production"]
            for row in development
        }
        self.assertEqual(sum(value == "reject" for value in decisions.values()), 5)
        self.assertEqual(decisions[40], "reject")
        self.assertEqual(decisions[1], "accept")
        with self.assertRaisesRegex(ValueError, "unique"):
            duplicate = dict(dataset)
            duplicate["splits"] = dict(dataset["splits"])
            duplicate["splits"]["hard_negatives"] = [development[0], development[0]]
            validate_dataset(duplicate)

    def test_split_selection_is_stable_and_covers_hard_negative_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self._dataset(directory)
            second = self._dataset(directory)
        self.assertEqual(first, second)
        tags = {
            tag for row in first["splits"]["hard_negatives"]
            for tag in row["tags"]
        }
        self.assertTrue({
            "wrong_sense", "nearby_wrong_subtitle", "larger_expression",
            "homograph_or_alternate_reading", "fragment", "slang", "one_word",
        }.issubset(tags))
        self.assertTrue(all(
            row["review_status"] == "unreviewed"
            for split in ("heldout_hxh", "second_show")
            for row in first["splits"][split]
        ))

    def test_metrics_count_false_accepts_and_insufficient_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._dataset(directory)
        gold = [
            row for split in ("development", "hard_negatives")
            for row in dataset["splits"][split]
        ]
        predictions = {
            "model": "candidate-model",
            "prompt_versions": dataset["prompt_versions"],
            "summary": {"cards_per_second": 3.5, "peak_memory_gb": 1.2},
            "records": [
                {
                    "case_id": row["case_id"], "accepted": True,
                    "abstained": False, "sense_votes": ["sense", "sense"],
                    "reason": "accepted",
                }
                for row in gold
            ],
        }
        report = evaluate_predictions(dataset, predictions)
        expected_rejects = sum(
            row["labels"]["production"] == "reject" for row in gold
        )
        self.assertEqual(report["summary"]["false_accepts"], expected_rejects)
        self.assertEqual(report["summary"]["cards_per_second"], 3.5)
        tagged = report["subgroups"]["near_duplicate_learning_unit"]
        self.assertIn("accepted_precision_95ci", tagged)
        self.assertIn("invalid_output_rate", tagged)
        self.assertFalse(report["summary"]["precision_claim_supported"])
        self.assertEqual(report["summary"]["precision_claim_reason"], "insufficient_accepted_gold")

    def test_precision_claim_uses_confidence_bound_and_minimum_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._dataset(directory)
        accepted_gold = [
            row for row in dataset["splits"]["development"]
            if row["labels"]["production"] == "accept"
        ]
        predictions = {
            "prompt_versions": dataset["prompt_versions"],
            "records": [
                {"case_id": row["case_id"], "accepted": True, "abstained": False}
                for row in accepted_gold
            ],
        }
        report = evaluate_predictions(
            dataset, predictions, precision_target=0.90,
            minimum_accepted_gold=len(accepted_gold),
        )
        self.assertTrue(report["summary"]["precision_claim_supported"])

    def test_report_is_blinded_and_gold_is_revealable(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._dataset(directory)
            predictions = {
                "model": "secret-model-name",
                "prompt_versions": dataset["prompt_versions"],
                "records": [],
            }
            report = evaluate_predictions(dataset, predictions)
            output = render_blinded_html(dataset, report, Path(directory) / "report.html")
            rendered = output.read_text(encoding="utf-8")
        self.assertIn("Reveal gold judgment", rendered)
        self.assertIn("Candidate ", rendered)
        self.assertNotIn("secret-model-name", rendered)

    def test_mismatched_prompt_versions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = self._dataset(directory)
        with self.assertRaisesRegex(ValueError, "prompt/rule versions"):
            evaluate_predictions(dataset, {"prompt_versions": {}, "records": []})


if __name__ == "__main__":
    unittest.main()
