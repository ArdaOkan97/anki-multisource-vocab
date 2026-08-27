import json
import tempfile
import unittest
from pathlib import Path

from vocabdeck.comparison import (
    compare_card_sets, load_card_artifact, render_comparison_html,
    write_comparison_json,
)


def card(key, position, **changes):
    value = {
        "position": position,
        "learning_unit_key": key,
        "lexeme_key": key.split("::", 1)[0],
        "sense_key": key.split("::", 1)[1],
        "sentence_id": position,
        "lemma": f"word-{key}",
        "reading": f"reading-{key}",
        "part_of_speech": "名詞",
        "gloss": f"gloss-{key}",
        "japanese": f"sentence-{key}",
        "english": f"translation-{key}",
        "season": 1,
        "episode": 1,
        "cue_index": position,
        "start_ms": position * 100,
        "end_ms": position * 100 + 50,
        "unknown_context_words": 0,
    }
    value.update(changes)
    return value


class ComparisonTest(unittest.TestCase):
    def test_reports_structural_and_categorized_card_changes(self):
        baseline = [card("a::s1", 1), card("b::s1", 2), card("c::s1", 3)]
        changed_b = dict(baseline[1])
        changed_b.update(reading="new-reading", english="new translation")
        candidate = [
            changed_b,
            dict(baseline[0]),
            card("d::s1", 3),
        ]

        report = compare_card_sets(baseline, candidate)

        self.assertEqual(report["summary"]["retained"], 2)
        self.assertEqual(report["summary"]["removed"], 1)
        self.assertEqual(report["summary"]["added"], 1)
        self.assertEqual(report["summary"]["reordered"], 1)
        self.assertEqual(report["summary"]["learner_visible_changed"], 1)
        self.assertEqual(report["changed"][0]["categories"], ["reading", "translation"])

    def test_position_shifts_from_removal_are_not_reorderings(self):
        baseline = [card("a::s1", 1), card("b::s1", 2), card("c::s1", 3)]
        candidate = [card("b::s1", 1), card("c::s1", 2)]

        report = compare_card_sets(baseline, candidate)

        self.assertEqual(report["summary"]["reordered"], 0)

    def test_same_lexeme_new_sense_is_reported_as_sense_replacement(self):
        baseline = [card("a::s1", 1)]
        candidate = [card("a::s2", 1, gloss="different sense")]

        report = compare_card_sets(baseline, candidate)

        self.assertEqual(report["summary"]["removed"], 1)
        self.assertEqual(report["summary"]["added"], 1)
        self.assertEqual(report["summary"]["sense_replacements"], 1)
        self.assertIn("sense", report["replacements"][0]["categories"])

    def test_checks_curriculum_limits_and_human_findings(self):
        baseline = [card(f"k{position}::s1", position) for position in range(1, 22)]
        candidate = [dict(item) for item in baseline]
        candidate[0]["unknown_context_words"] = 1
        candidate[4]["start_ms"] += 10
        review = {
            "flagged_cards": [
                {"position": 5, "categories": ["audio_quality"], "user_note": "bad audio"},
                {"position": 6, "categories": ["translation_quality"], "user_note": "bad text"},
                {"position": 7, "categories": ["semantic_duplicate"], "user_note": "duplicate"},
            ]
        }
        candidate = [item for item in candidate if item["position"] != 7]

        report = compare_card_sets(baseline, candidate, human_review=review)

        self.assertFalse(report["checks"]["curriculum_unknown_words"]["passed"])
        findings = report["checks"]["human_findings"]
        self.assertEqual([item["status"] for item in findings], ["changed", "unchanged", "removed"])
        self.assertTrue(findings[0]["manual_confirmation_required"])

    def test_loads_array_or_selection_and_writes_both_reports(self):
        cards = [card("a::s1", 1)]
        report = compare_card_sets(cards, cards)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            array_path = root / "array.json"
            selection_path = root / "selection.json"
            array_path.write_text(json.dumps(cards), encoding="utf-8")
            selection_path.write_text(json.dumps({"accepted": cards}), encoding="utf-8")
            self.assertEqual(load_card_artifact(array_path), cards)
            self.assertEqual(load_card_artifact(selection_path), cards)
            json_path = write_comparison_json(report, root / "report.json")
            html_path = render_comparison_html(report, root / "report.html")
            self.assertEqual(json.loads(json_path.read_text())["schema_version"], 1)
            self.assertIn("Vocabulary baseline comparison", html_path.read_text())


if __name__ == "__main__":
    unittest.main()
