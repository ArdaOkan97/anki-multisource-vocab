import tempfile
import unittest
from pathlib import Path

from vocabdeck.constrained_review import (
    build_sense_prompt,
    build_support_prompt,
    parse_label,
    run_constrained_benchmark,
    run_constrained_curriculum,
    run_constrained_dataset,
    sense_options,
)
from vocabdeck.inference_resources import InferenceResourceGuard


class FakeReviewer:
    model_name = "fake-small"

    def __init__(self, responses):
        self.responses = iter(responses)

    def review(self, prompts):
        values = [next(self.responses) for _ in prompts]
        return values, {
            "prompt_tokens": len(prompts) * 10,
            "generation_tokens": len(prompts),
            "prompt_time": 0.1,
            "generation_time": 0.1,
            "peak_memory": 1.25,
        }


class FakeResolver:
    class Match:
        def __init__(self, gloss, entry_id, sense_index):
            self.gloss = gloss
            self.entry_id = entry_id
            self.sense_index = sense_index

    def sense_candidates(self, *args):
        return (
            self.Match("first meaning", 100, 0),
            self.Match("second meaning", 100, 1),
        )


def card():
    return {
        "audit_position": 1,
        "candidate_key": "candidate-1",
        "learning_unit_key": "word::jmdict:100:1",
        "sense_key": "jmdict:100:1",
        "lemma": "語",
        "reading": "ゴ",
        "part_of_speech": "名詞",
        "target_surface": "語",
        "japanese": "この語を使う。",
        "english": "Use this word.",
    }


class ConstrainedReviewTest(unittest.TestCase):
    def test_curriculum_reviews_teachable_frontiers_until_complete(self):
        value = card()
        value.update({
            "gloss": "second meaning",
            "target_start": 2,
            "target_end": 3,
            "sentence_id": 10,
            "curriculum_position": 1,
            "candidate_position": 1,
            "difficulty_score": 1.0,
            "context_learning_unit_keys": ["word::jmdict:100:1"],
            "initial_known_context_learning_unit_keys": [],
            "example_progression": {"content_words": 2, "selection_score": 1.0},
            "audit_findings": [],
            "audit_criteria": [
                {"code": code, "status": "passed"}
                for code in (
                    "translation_available", "translation_alignment",
                    "translation_scope", "definition_available",
                    "contextual_interpretation", "gloss_support",
                    "context_difficulty", "contextual_reading",
                    "expression_interpretation", "unique_example",
                )
            ],
        })
        options = sense_options(value, FakeResolver())
        labels = [
            next(
                label for label, identity in
                build_sense_prompt(value, options, round_index).label_to_sense.items()
                if identity == value["sense_key"]
            )
            for round_index in (1, 2)
        ]
        result = run_constrained_curriculum(
            [value], FakeReviewer([*labels, "A"]), limit=1,
            resolver=FakeResolver(),
        )

        self.assertTrue(result["selection"]["summary"]["complete"])
        self.assertEqual(result["selection"]["summary"]["accepted"], 1)
        self.assertEqual(result["predictions"]["summary"]["evaluated"], 1)
        self.assertEqual(result["predictions"]["summary"]["rounds"], 1)

    def test_too_many_senses_abstains_instead_of_crashing(self):
        class ManySenseResolver:
            def sense_candidates(self, *args):
                return tuple(
                    FakeResolver.Match(f"meaning {index}", 100, index)
                    for index in range(26)
                )

        result = run_constrained_benchmark(
            [card()], FakeReviewer([]), {1: True},
            resolver=ManySenseResolver(),
        )

        self.assertEqual(result["summary"]["accepted"], 0)
        self.assertEqual(result["records"][0]["reason"], "too_many_sense_options")

    def test_sense_options_honor_verb_te_construction(self):
        value = card()
        value.update({
            "lemma": "くれる", "reading": "クレル",
            "part_of_speech": "動詞",
            "japanese": "さて １つ答えてくれ。", "target_start": 8,
        })

        options = sense_options(value)

        self.assertEqual(
            [option["sense_key"] for option in options], ["jmdict:1269130:2"]
        )

    def test_resource_guard_rejects_oversized_model_before_load(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model"
            model.mkdir()
            (model / "weights.safetensors").write_bytes(b"x" * 1024)
            guard = InferenceResourceGuard(max_model_artifact_gb=0.0000001)
            with self.assertRaisesRegex(RuntimeError, "safety ceiling"):
                guard.validate_model_path(model)

    def test_resource_guard_prevents_overlapping_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "inference.lock"
            first = InferenceResourceGuard(lock_path=lock)
            second = InferenceResourceGuard(lock_path=lock)
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    second.acquire()
            finally:
                first.release()

    def test_resource_guard_rejects_unsafe_memory_override(self):
        with self.assertRaisesRegex(ValueError, "no more than 6 GiB"):
            InferenceResourceGuard(memory_limit_gb=6.1)

    def test_resource_guard_configures_mlx_below_hard_ceiling(self):
        class FakeMLX:
            memory_limit = None
            cache_limit = None

            def set_memory_limit(self, value):
                self.memory_limit = value

            def set_cache_limit(self, value):
                self.cache_limit = value

        fake = FakeMLX()
        InferenceResourceGuard().configure_mlx(fake)
        self.assertEqual(fake.memory_limit, 4 * 1024**3)
        self.assertEqual(fake.cache_limit, 512 * 1024**2)

    def test_sense_options_shuffle_but_map_to_stable_identity(self):
        options = [
            {"sense_key": "jmdict:100:0", "gloss": "first"},
            {"sense_key": "jmdict:100:1", "gloss": "second"},
        ]
        first = build_sense_prompt(card(), options, 1)
        second = build_sense_prompt(card(), options, 2)
        self.assertEqual(set(first.label_to_sense.values()), {
            "jmdict:100:0", "jmdict:100:1", None,
        })
        self.assertEqual(set(second.label_to_sense.values()), {
            "jmdict:100:0", "jmdict:100:1", None,
        })
        self.assertTrue(first.prompt.rstrip().endswith("None of these / ambiguous"))
        self.assertTrue(second.prompt.rstrip().endswith("None of these / ambiguous"))

    def test_prompt_v2_is_conservative_and_requires_bare_label(self):
        options = [
            {"sense_key": "jmdict:100:0", "gloss": "first"},
            {"sense_key": "jmdict:100:1", "gloss": "second"},
        ]
        sense = build_sense_prompt(card(), options, 1, prompt_version=2)
        support = build_support_prompt(card(), "word", prompt_version=2)

        self.assertIn("context is insufficient", sense.prompt)
        self.assertIn("larger expression", sense.prompt)
        self.assertIn("Do not repeat the option text", sense.prompt)
        self.assertIn("contamination or misalignment", support.prompt)
        self.assertIn("natural paraphrase", support.prompt)
        self.assertTrue(sense.prompt.endswith("Answer:"))
        self.assertTrue(support.prompt.endswith("Answer:"))

    def test_prompt_v1_remains_the_default(self):
        options = [{"sense_key": "jmdict:100:0", "gloss": "first"}]
        prompt = build_sense_prompt(card(), options, 1)

        self.assertTrue(prompt.prompt.startswith(
            "Choose the meaning of the marked Japanese word in this sentence."
        ))
        self.assertNotIn("conservative Japanese lexical-sense", prompt.prompt)

    def test_invalid_or_ambiguous_labels_fail_closed(self):
        prompt = build_support_prompt(card(), "word")
        self.assertEqual(parse_label("A", prompt.label_to_sense), "expressed")
        self.assertIsNone(parse_label("C", prompt.label_to_sense))
        self.assertEqual(
            parse_label("A\n<end_of_turn>", prompt.label_to_sense), "expressed"
        )
        with self.assertRaises(ValueError):
            parse_label("The answer is A", prompt.label_to_sense)

    def test_benchmark_requires_two_sense_votes_then_separate_support(self):
        options = [
            {"sense_key": "jmdict:100:0", "gloss": "first meaning"},
            {"sense_key": "jmdict:100:1", "gloss": "second meaning"},
        ]
        prompts = [build_sense_prompt(card(), options, value) for value in (1, 2)]
        sense_labels = []
        for prompt in prompts:
            sense_labels.append(next(
                label for label, identity in prompt.label_to_sense.items()
                if identity == "jmdict:100:1"
            ))
        result = run_constrained_benchmark(
            [card()],
            FakeReviewer([*sense_labels, "A"]),
            {1: True},
            resolver=FakeResolver(),
            precision_target=0.99,
        )
        self.assertEqual(result["summary"]["accepted"], 1)
        self.assertEqual(result["summary"]["false_accepts"], 0)
        self.assertEqual(result["records"][0]["sense_raw"], sense_labels)
        self.assertTrue(result["summary"]["adopt"])

    def test_false_accept_blocks_adoption(self):
        options = [
            {"sense_key": "jmdict:100:0", "gloss": "first meaning"},
            {"sense_key": "jmdict:100:1", "gloss": "second meaning"},
        ]
        labels = []
        for value in (1, 2):
            prompt = build_sense_prompt(card(), options, value)
            labels.append(next(
                label for label, identity in prompt.label_to_sense.items()
                if identity == "jmdict:100:1"
            ))
        result = run_constrained_benchmark(
            [card()], FakeReviewer([*labels, "A"]), {1: False},
            resolver=FakeResolver(), precision_target=0.995,
        )
        self.assertEqual(result["summary"]["false_accepts"], 1)
        self.assertFalse(result["summary"]["adopt"])

    def test_dataset_runner_preserves_case_ids_and_prompt_versions(self):
        options = [
            {"sense_key": "jmdict:100:0", "gloss": "first meaning"},
            {"sense_key": "jmdict:100:1", "gloss": "second meaning"},
        ]
        labels = []
        for value in (1, 2):
            prompt = build_sense_prompt(card(), options, value)
            labels.append(next(
                label for label, identity in prompt.label_to_sense.items()
                if identity == "jmdict:100:1"
            ))
        dataset = {
            "prompt_versions": {
                "sense": 1, "subtitle_support": 1, "acceptance_policy": 1,
            },
            "splits": {"development": [{"case_id": "case-1", "card": card()}]},
        }
        result = run_constrained_dataset(
            dataset, FakeReviewer([*labels, "A"]), resolver=FakeResolver()
        )
        self.assertEqual(result["records"][0]["case_id"], "case-1")
        self.assertTrue(result["records"][0]["accepted"])
        self.assertEqual(result["prompt_versions"], dataset["prompt_versions"])

    def test_dataset_runner_rejects_changed_prompt_policy(self):
        with self.assertRaisesRegex(ValueError, "prompt/rule versions"):
            run_constrained_dataset(
                {"prompt_versions": {}, "splits": {}}, FakeReviewer([]),
                resolver=FakeResolver(),
            )

    def test_dataset_runner_can_ab_test_prompt_v2_on_same_cases(self):
        options = [
            {"sense_key": "jmdict:100:0", "gloss": "first meaning"},
            {"sense_key": "jmdict:100:1", "gloss": "second meaning"},
        ]
        labels = []
        for value in (1, 2):
            prompt = build_sense_prompt(
                card(), options, value, prompt_version=2,
            )
            labels.append(next(
                label for label, identity in prompt.label_to_sense.items()
                if identity == "jmdict:100:1"
            ))
        dataset = {
            "prompt_versions": {
                "sense": 1, "subtitle_support": 1, "acceptance_policy": 1,
            },
            "splits": {"development": [{"case_id": "case-1", "card": card()}]},
        }

        result = run_constrained_dataset(
            dataset, FakeReviewer([*labels, "A"]), resolver=FakeResolver(),
            prompt_version=2,
        )

        self.assertTrue(result["records"][0]["accepted"])
        self.assertEqual(result["prompt_versions"]["sense"], 2)


if __name__ == "__main__":
    unittest.main()
