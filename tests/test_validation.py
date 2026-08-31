import unittest

from vocabdeck.local_review import card_fingerprint
from vocabdeck.validation import (
    DeterministicCardValidator,
    RecordedReviewValidator,
    UnanimousCardValidator,
    plan_review_frontier,
    select_validated_curriculum,
    validate_cards,
)


def audited_card(part_of_speech="動詞"):
    criteria = [
        {"code": code, "status": "passed"}
        for code in (
            "translation_available", "translation_alignment",
            "definition_available", "contextual_interpretation",
            "gloss_support", "context_difficulty",
            "expression_interpretation", "unique_example",
        )
    ]
    criteria.append({
        "code": "contextual_reading",
        "status": "not_checked" if part_of_speech == "動詞" else "passed",
    })
    return {
        "audit_position": 1,
        "lexeme_key": "taberu",
        "lemma": "食べる",
        "reading": "タベル",
        "part_of_speech": part_of_speech,
        "gloss": "to eat",
        "target_surface": "食べる",
        "target_start": 0,
        "target_end": 3,
        "japanese": "食べる。",
        "english": "I'll eat it.",
        "audit_findings": [],
        "audit_criteria": criteria,
        "example_progression": {"content_words": 1},
    }


def review(card, review_pass, verdict="correct", reason="supported"):
    return {
        "audit_position": card["audit_position"],
        "review_pass": review_pass,
        "card_fingerprint": card_fingerprint(card, review_pass=review_pass),
        "verdict": verdict,
        "reason_code": reason,
    }


class ValidationTest(unittest.TestCase):
    def test_distinct_senses_of_one_lexeme_are_separate_curriculum_targets(self):
        reaction = audited_card()
        reaction.update({
            "audit_position": 1, "curriculum_position": 1,
            "candidate_position": 1, "sentence_id": 10,
            "lexeme_id": 10, "lexeme_key": "sou",
            "sense_key": "jmdict:2137720:2",
            "learning_unit_key": "sou::jmdict:2137720:2",
            "difficulty_score": 10.0,
            "context_learning_unit_keys": ["sou::jmdict:2137720:2"],
            "initial_known_context_learning_unit_keys": [],
        })
        manner = dict(reaction)
        manner.update({
            "audit_position": 2, "curriculum_position": 2,
            "sentence_id": 20,
            "sense_key": "jmdict:2137720:0",
            "learning_unit_key": "sou::jmdict:2137720:0",
            "context_learning_unit_keys": ["sou::jmdict:2137720:0"],
        })
        validation = {
            "accepted": [
                {"audit_position": position, "decision": {"status": "accepted"}}
                for position in (1, 2)
            ],
            "rejected": [], "abstained": [],
        }

        selection = select_validated_curriculum(
            [reaction, manner], validation
        )

        self.assertEqual(selection["summary"]["accepted"], 2)
        self.assertEqual(
            {card["sense_key"] for card in selection["accepted"]},
            {"jmdict:2137720:0", "jmdict:2137720:2"},
        )

    def test_review_fingerprint_includes_sense_identity(self):
        first = audited_card()
        first.update({
            "sense_key": "jmdict:2137720:0",
            "learning_unit_key": "sou::jmdict:2137720:0",
        })
        second = dict(first)
        second.update({
            "sense_key": "jmdict:2137720:2",
            "learning_unit_key": "sou::jmdict:2137720:2",
        })

        self.assertNotEqual(card_fingerprint(first), card_fingerprint(second))

    def test_review_frontier_plans_only_currently_teachable_targets(self):
        dependent = audited_card()
        dependent.update({
            "audit_position": 1, "curriculum_position": 1,
            "candidate_position": 1, "sentence_id": 10,
            "lexeme_id": 10, "difficulty_score": 10.0,
            "context_lexeme_ids": [10, 20],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [20],
        })
        prerequisite = audited_card()
        prerequisite.update({
            "audit_position": 2, "curriculum_position": 2,
            "candidate_position": 1, "sentence_id": 20,
            "lexeme_id": 20, "lexeme_key": "watashi", "lemma": "私",
            "difficulty_score": 11.0,
            "context_lexeme_ids": [20],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [],
        })

        plan = plan_review_frontier([dependent, prerequisite])

        self.assertEqual(plan["summary"]["planned_reviews"], 1)
        self.assertEqual(plan["cards"][0]["lexeme_id"], 20)
        self.assertEqual(
            plan["cards"][0]["review_planning"]["missing_review_passes"],
            ["contextual", "recoverability", "contextual_gloss"],
        )

    def test_review_frontier_does_not_requeue_recorded_uncertainty(self):
        card = audited_card()
        card.update({
            "audit_position": 1, "curriculum_position": 1,
            "candidate_position": 1, "sentence_id": 10,
            "lexeme_id": 10, "difficulty_score": 10.0,
            "context_lexeme_ids": [10],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [],
        })
        uncertain = review(
            card, "contextual", verdict="uncertain",
            reason="insufficient_context",
        )

        plan = plan_review_frontier(
            [card], reviews_by_pass={"contextual": [uncertain]}
        )

        self.assertEqual(plan["summary"]["planned_reviews"], 0)

    def test_deterministic_gate_fails_closed(self):
        validator = DeterministicCardValidator()
        self.assertEqual(validator.validate(audited_card()).status, "accepted")

        flagged = audited_card()
        flagged["audit_findings"] = [{"code": "weak_gloss_support"}]
        result = validator.validate(flagged)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason_codes, ("audit:weak_gloss_support",))

        harder_context = audited_card()
        harder_context["audit_findings"] = [
            {"code": "harder_unknown_context"}
        ]
        next(
            item for item in harder_context["audit_criteria"]
            if item["code"] == "context_difficulty"
        )["status"] = "flagged"
        self.assertEqual(validator.validate(harder_context).status, "accepted")

        incomplete = audited_card("名詞")
        next(
            item for item in incomplete["audit_criteria"]
            if item["code"] == "contextual_reading"
        )["status"] = "not_checked"
        result = validator.validate(incomplete)
        self.assertEqual(result.status, "abstained")
        self.assertIn(
            "unresolved_criterion:contextual_reading", result.reason_codes
        )

        compound = audited_card("名詞")
        compound.update({
            "lemma": "装甲", "reading": "ソウコウ", "gloss": "armor",
            "target_surface": "装甲", "target_end": 2,
            "japanese": "装甲車？", "english": "An armored vehicle?",
        })
        result = validator.validate(compound)
        self.assertEqual(result.status, "rejected")
        self.assertIn("untracked_kanji_context", result.reason_codes)

        oversized_translation = audited_card()
        oversized_translation["english"] = (
            "There is too much at stake without knowing what they have hidden. "
            "Given all of that, I shall continue."
        )
        result = validator.validate(oversized_translation)
        self.assertEqual(result.status, "rejected")
        self.assertIn("excess_translation_scope", result.reason_codes)

    def test_unanimous_pipeline_requires_context_and_recoverability(self):
        card = audited_card()
        contextual = review(card, "contextual")
        recoverability = review(card, "recoverability")
        contextual_gloss = review(card, "contextual_gloss")
        pipeline = UnanimousCardValidator([
            DeterministicCardValidator(),
            RecordedReviewValidator("contextual", [contextual]),
            RecordedReviewValidator("recoverability", [recoverability]),
            RecordedReviewValidator("contextual_gloss", [contextual_gloss]),
        ])
        self.assertEqual(pipeline.validate(card)["status"], "accepted")

        recoverability["verdict"] = "incorrect"
        recoverability["reason_code"] = "not_recoverable"
        pipeline = UnanimousCardValidator([
            DeterministicCardValidator(),
            RecordedReviewValidator("contextual", [contextual]),
            RecordedReviewValidator("recoverability", [recoverability]),
            RecordedReviewValidator("contextual_gloss", [contextual_gloss]),
        ])
        decision = pipeline.validate(card)
        self.assertEqual(decision["status"], "rejected")
        self.assertEqual(decision["failed_stage"], "llm:recoverability")

    def test_missing_review_abstains_and_is_counted(self):
        card = audited_card()
        pipeline = UnanimousCardValidator([
            DeterministicCardValidator(),
            RecordedReviewValidator("contextual", []),
        ])
        report = validate_cards([card], pipeline)
        self.assertEqual(report["summary"], {
            "accepted": 0, "rejected": 0, "abstained": 1,
        })
        self.assertEqual(
            report["abstained"][0]["decision"]["reason_codes"],
            ["missing_contextual_review"],
        )

    def test_curriculum_selection_preserves_targets_and_uses_unique_sentences(self):
        first = audited_card()
        first.update({
            "audit_position": 1, "curriculum_position": 1,
            "candidate_position": 1, "sentence_id": 10,
            "lexeme_id": 10, "difficulty_score": 10.0,
            "context_lexeme_ids": [10],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [],
        })
        alternate = dict(first)
        alternate.update({
            "audit_position": 2, "candidate_position": 2, "sentence_id": 11,
        })
        second = dict(first)
        second.update({
            "audit_position": 3, "curriculum_position": 2,
            "candidate_position": 1, "sentence_id": 10,
            "lexeme_id": 20, "difficulty_score": 11.0,
            "context_lexeme_ids": [20],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [],
            "lexeme_key": "nomu", "lemma": "飲む",
        })
        validation = {
            "accepted": [
                {"audit_position": value, "decision": {"status": "accepted"}}
                for value in (1, 2, 3)
            ],
            "rejected": [], "abstained": [],
        }
        selection = select_validated_curriculum(
            [first, alternate, second], validation
        )
        self.assertEqual(selection["summary"]["accepted"], 1)
        self.assertEqual(selection["summary"]["deferred"], 1)
        self.assertEqual(selection["accepted"][0]["sentence_id"], 10)

    def test_selection_limit_keeps_later_targets_deferred(self):
        cards = []
        accepted = []
        for position in range(1, 4):
            card = audited_card()
            card.update({
                "audit_position": position,
                "curriculum_position": position,
                "candidate_position": 1,
                "sentence_id": position,
                "lexeme_id": position,
                "lexeme_key": f"word-{position}",
                "difficulty_score": float(position),
                "context_lexeme_ids": [position],
                "initial_known_context_lexeme_ids": [],
                "initial_unknown_context_lexeme_ids": [],
            })
            cards.append(card)
            accepted.append({
                "audit_position": position,
                "decision": {"status": "accepted"},
            })

        selection = select_validated_curriculum(
            cards,
            {"accepted": accepted, "rejected": [], "abstained": []},
            limit=2,
        )

        self.assertEqual(selection["summary"]["accepted"], 2)
        self.assertEqual(selection["summary"]["deferred"], 1)
        self.assertTrue(selection["summary"]["complete"])

    def test_sentence_dependency_can_reorder_the_lexical_frontier(self):
        dependent = audited_card()
        dependent.update({
            "audit_position": 1, "curriculum_position": 1,
            "candidate_position": 1, "sentence_id": 10,
            "lexeme_id": 10, "difficulty_score": 10.0,
            "context_lexeme_ids": [10, 20],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [20],
        })
        prerequisite = audited_card()
        prerequisite.update({
            "audit_position": 2, "curriculum_position": 2,
            "candidate_position": 1, "sentence_id": 20,
            "lexeme_id": 20, "lexeme_key": "watashi", "lemma": "私",
            "difficulty_score": 11.0,
            "context_lexeme_ids": [20],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [],
        })
        validation = {
            "accepted": [
                {"audit_position": value, "decision": {"status": "accepted"}}
                for value in (1, 2)
            ],
            "rejected": [], "abstained": [],
        }

        selection = select_validated_curriculum(
            [dependent, prerequisite], validation
        )

        self.assertEqual(
            [card["lexeme_id"] for card in selection["accepted"]],
            [20, 10],
        )
        self.assertEqual(
            selection["accepted"][1]["scheduling"]["unknown_context_words"],
            0,
        )

    def test_missing_context_metadata_fails_closed(self):
        card = audited_card()
        card.update({
            "lexeme_id": 10, "difficulty_score": 10.0,
            "curriculum_position": 1, "candidate_position": 1,
            "sentence_id": 10,
        })
        validation = {
            "accepted": [{
                "audit_position": 1, "decision": {"status": "accepted"},
            }],
            "rejected": [], "abstained": [],
        }

        selection = select_validated_curriculum([card], validation)

        self.assertEqual(selection["summary"]["accepted"], 0)
        self.assertIn(
            "missing_context_metadata", selection["deferred"][0]["blockers"]
        )

    def test_harder_unknown_fails_even_when_count_allowance_permits_it(self):
        card = audited_card()
        card.update({
            "lexeme_id": 10, "difficulty_score": 10.0,
            "curriculum_position": 1, "candidate_position": 1,
            "sentence_id": 10,
            "context_lexeme_ids": [10, 20],
            "initial_known_context_lexeme_ids": [],
            "initial_unknown_context_lexeme_ids": [20],
        })
        context_target = dict(card)
        context_target.update({
            "audit_position": 2, "lexeme_id": 20,
            "difficulty_score": 50.0, "curriculum_position": 2,
            "sentence_id": 20, "context_lexeme_ids": [20],
        })
        validation = {
            "accepted": [{
                "audit_position": 1, "decision": {"status": "accepted"},
            }],
            "rejected": [{
                "audit_position": 2, "decision": {"status": "rejected"},
            }],
            "abstained": [],
        }

        selection = select_validated_curriculum(
            [card, context_target], validation,
            zero_unknown_through=0,
        )

        self.assertEqual(selection["summary"]["accepted"], 0)
        self.assertIn(
            "harder_unknown_context", selection["deferred"][0]["blockers"]
        )

    def test_compound_suffix_dependency_is_not_hidden_by_known_prefix(self):
        card = audited_card()
        target = "honmono::real"
        examiner_prefix = "shiken::exam"
        examiner_suffix = "kan::official"
        speaker = "ore::i"
        card.update({
            "lexeme_id": 10,
            "learning_unit_key": target,
            "difficulty_score": 10.0,
            "curriculum_position": 1,
            "candidate_position": 1,
            "sentence_id": 1134,
            "japanese": "俺が本物の試験官だ！",
            "target_surface": "本物",
            "target_start": 2,
            "target_end": 4,
            "context_learning_unit_keys": [
                speaker, target, examiner_prefix, examiner_suffix,
            ],
            "initial_known_context_learning_unit_keys": [
                speaker, examiner_prefix,
            ],
        })
        validation = {
            "accepted": [{
                "audit_position": 1,
                "decision": {"status": "accepted"},
            }],
            "rejected": [{
                "audit_position": 2,
                "decision": {"status": "rejected"},
            }],
            "abstained": [],
        }
        suffix_target = audited_card()
        suffix_target.update({
            "audit_position": 2,
            "lexeme_id": 20,
            "learning_unit_key": examiner_suffix,
            "difficulty_score": 9.0,
            "curriculum_position": 2,
            "candidate_position": 1,
            "sentence_id": 2000,
            "context_learning_unit_keys": [examiner_suffix],
            "initial_known_context_learning_unit_keys": [],
        })

        selection = select_validated_curriculum(
            [card, suffix_target], validation,
            zero_unknown_through=0,
        )

        self.assertEqual(selection["summary"]["accepted"], 1)
        self.assertEqual(
            selection["accepted"][0]["scheduling"][
                "unknown_context_learning_unit_keys"
            ],
            [examiner_suffix],
        )
        self.assertEqual(
            selection["accepted"][0]["scheduling"]["unknown_context_words"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
