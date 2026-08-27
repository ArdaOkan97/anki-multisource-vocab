import hashlib
import json
import unittest
from pathlib import Path


BASELINE = (
    Path(__file__).parents[1]
    / "baselines"
    / "hxh-e01-e10-hybrid-qwen9b-200-v1"
)


class BaselineSnapshotTest(unittest.TestCase):
    def test_reviewed_hybrid_baseline_is_immutable_and_self_consistent(self):
        config_path = BASELINE / "config.json"
        cards_path = BASELINE / "expected-cards.json"
        review_path = BASELINE / "human-review.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        raw_cards = cards_path.read_bytes()
        cards = json.loads(raw_cards)
        review = json.loads(review_path.read_text(encoding="utf-8"))

        self.assertEqual(
            hashlib.sha256(raw_cards).hexdigest(),
            config["expected_cards_sha256"],
        )
        self.assertEqual(len(cards), 200)
        self.assertEqual(
            [card["position"] for card in cards], list(range(1, 201))
        )
        self.assertEqual(len({card["sentence_id"] for card in cards}), 200)
        self.assertEqual(
            len({card["learning_unit_key"] for card in cards}), 200
        )
        self.assertTrue(
            all(card["unknown_context_words"] == 0 for card in cards[:20])
        )
        self.assertTrue(
            all(card["unknown_context_words"] <= 1 for card in cards[20:])
        )
        expected_stages = [
            "deterministic",
            "llm:contextual",
            "llm:recoverability",
            "llm:contextual_gloss",
        ]
        self.assertTrue(
            all(card["validation_stages"] == expected_stages for card in cards)
        )
        self.assertTrue(config["local_model_validation"]["enabled"])
        self.assertTrue(config["disabled_features"]["hosted_llm"])
        self.assertFalse(
            config["disabled_features"].get("local_model_validation", False)
        )
        self.assertEqual(review["reviewed_cards"], 100)
        self.assertEqual(
            len(review["flagged_cards"]),
            config["human_review"]["flagged_cards"],
        )
        self.assertEqual(
            [item["position"] for item in review["flagged_cards"]],
            [40, 56, 68, 69, 78],
        )


if __name__ == "__main__":
    unittest.main()
