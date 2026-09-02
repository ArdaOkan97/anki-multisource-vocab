import json
import unittest
from pathlib import Path

from vocabdeck.small_verifier_benchmark import (
    build_comparison_report,
    build_smoke_dataset,
    load_candidate_config,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = json.loads(
    (ROOT / "benchmarks/verifier-gold-v1/dataset.json").read_text(encoding="utf-8")
)


class SmallVerifierBenchmarkTest(unittest.TestCase):
    def test_smoke_is_stable_gold_only_and_balanced(self):
        first = build_smoke_dataset(DATASET)
        second = build_smoke_dataset(DATASET)
        self.assertEqual(first, second)
        rows = first["splits"]["smoke"]
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(row["review_status"] == "gold" for row in rows))
        self.assertEqual(
            sum(row["labels"]["production"] == "reject" for row in rows), 10
        )

    def test_config_pins_three_required_candidates(self):
        config = load_candidate_config(
            ROOT / "benchmarks/small-verifier-v1/config.json"
        )
        self.assertEqual(set(config), {
            "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            "mlx-community/gemma-2-2b-jpn-it-4bit",
            "mlx-community/Qwen3-1.7B-4bit",
            "mlx-community/Phi-4-mini-instruct-4bit",
        })
        self.assertTrue(all(len(row["revision"]) == 40 for row in config.values()))

    def test_comparison_refuses_adoption_without_sufficient_evidence(self):
        evaluation = {
            "model": "candidate@revision",
            "summary": {
                "cleanup_verified": True,
                "precision_claim_supported": False,
                "accepted_precision": 1.0,
                "positive_coverage": 0.5,
            },
            "subgroups": {},
        }
        report = build_comparison_report([evaluation], {})
        self.assertEqual(
            report["recommendation"]["decision"],
            "retain_deterministic_baseline",
        )

    def test_comparison_rejects_incomplete_cleanup(self):
        evaluation = {
            "model": "candidate@revision",
            "summary": {
                "cleanup_verified": False,
                "precision_claim_supported": True,
                "accepted_precision": 1.0,
                "positive_coverage": 1.0,
            },
        }
        report = build_comparison_report([evaluation], {})
        self.assertEqual(report["candidates"][0]["status"], "resource_or_cleanup_failure")
        self.assertEqual(
            report["recommendation"]["decision"],
            "retain_deterministic_baseline",
        )


if __name__ == "__main__":
    unittest.main()
