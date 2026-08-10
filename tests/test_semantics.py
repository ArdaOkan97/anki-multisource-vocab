import unittest
import tempfile
from pathlib import Path

from vocabdeck.semantics import ExpressionSemanticScorer, MultilingualE5Small


class FakeEmbedder:
    model_name = "fake-embedder@1"

    def __init__(self, scores):
        self.scores = scores

    def similarity(self, query, passage):
        return self.scores[(query, passage)]


class FakeModel:
    def __init__(self):
        self.calls = []

    def encode(self, text, **kwargs):
        self.calls.append(text)
        return [1.0, 0.0] if text.startswith("query:") else [0.0, 1.0]


class ExpressionSemanticScorerTest(unittest.TestCase):
    def test_e5_embeddings_are_reused_from_persistent_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "embeddings.sqlite3"
            first_model = FakeModel()
            first = MultilingualE5Small(
                cache_path=cache, model_factory=lambda: first_model
            )
            self.assertEqual(first.similarity("hello", "world"), 0.0)
            self.assertEqual(len(first_model.calls), 2)

            second_model = FakeModel()
            second = MultilingualE5Small(
                cache_path=cache, model_factory=lambda: second_model
            )
            self.assertEqual(second.similarity("hello", "world"), 0.0)
            self.assertEqual(second_model.calls, [])

    def test_accepts_phrase_with_high_score_and_clear_margin(self):
        english = "Thank you."
        component = "Meaning composed from: how; in what way; how about"
        scorer = ExpressionSemanticScorer(
            FakeEmbedder({
                (english, "thank you; thanks"): 0.94,
                (english, "somehow; apparently"): 0.55,
                (english, component): 0.42,
            }),
            minimum_phrase_score=0.80,
            minimum_margin=0.08,
        )

        result = scorer.decide(
            english,
            ["thank you; thanks", "somehow; apparently"],
            ["how; in what way; how about"],
        )

        self.assertEqual(result.decision, "expression")
        self.assertEqual(result.phrase_description, "thank you; thanks")
        self.assertAlmostEqual(result.margin, 0.52)

    def test_keeps_components_when_they_fit_better(self):
        english = "I really do love that look."
        component = "Meaning composed from: good; excellent | face; expression; look"
        scorer = ExpressionSemanticScorer(
            FakeEmbedder({
                (english, "big shot; influential person"): 0.31,
                (english, component): 0.86,
                ("big shot; influential person", component): 0.40,
            })
        )

        result = scorer.decide(
            english,
            ["big shot; influential person"],
            ["good; excellent", "face; expression; look"],
        )

        self.assertEqual(result.decision, "components")
        self.assertGreater(result.component_score, result.phrase_score)

    def test_does_not_merge_a_narrow_phrase_win(self):
        english = "Maybe."
        component = "Meaning composed from: component"
        scorer = ExpressionSemanticScorer(
            FakeEmbedder({
                (english, "phrase"): 0.84,
                (english, component): 0.80,
            })
        )

        result = scorer.decide(english, ["phrase"], ["component"])

        self.assertEqual(result.decision, "ambiguous")

    def test_does_not_merge_transparently_compositional_phrase(self):
        english = "What will you do?"
        phrase = "what would you do?; what to do about it"
        component = "Meaning composed from: how; in what way | to do; to perform"
        scorer = ExpressionSemanticScorer(
            FakeEmbedder({
                (english, phrase): 0.91,
                (english, component): 0.82,
                (phrase, component): 0.90,
            })
        )

        result = scorer.decide(
            english, [phrase], ["how; in what way", "to do; to perform"]
        )

        self.assertEqual(result.decision, "ambiguous")
        self.assertAlmostEqual(result.opacity, 0.10)

    def test_opaque_multi_component_phrase_allows_smaller_margin(self):
        english = "I'm very sorry!"
        phrase = "I'm sorry; I feel regretful"
        component = "Meaning composed from: apology; excuse | not; without"
        scorer = ExpressionSemanticScorer(
            FakeEmbedder({
                (english, phrase): 0.85,
                (english, component): 0.82,
                (phrase, component): 0.80,
            })
        )

        result = scorer.decide(
            english,
            [phrase],
            ["apology; excuse", "not; without"],
            standalone=True,
        )

        self.assertEqual(result.decision, "expression")
        self.assertAlmostEqual(result.margin, 0.03)
        self.assertAlmostEqual(result.opacity, 0.20)

    def test_embedded_multi_component_phrase_keeps_full_margin(self):
        english = "Please accept my apology and continue."
        phrase = "I'm sorry; I feel regretful"
        component = "Meaning composed from: apology; excuse | not; without"
        scorer = ExpressionSemanticScorer(
            FakeEmbedder({
                (english, phrase): 0.85,
                (english, component): 0.82,
                (phrase, component): 0.80,
            })
        )

        result = scorer.decide(
            english, [phrase], ["apology; excuse", "not; without"]
        )

        self.assertEqual(result.decision, "ambiguous")

    def test_missing_translation_is_insufficient_evidence(self):
        scorer = ExpressionSemanticScorer(FakeEmbedder({}))

        result = scorer.decide("", ["thank you"], ["how"])

        self.assertEqual(result.decision, "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
