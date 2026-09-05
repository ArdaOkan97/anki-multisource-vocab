import pytest

from test_validation import audited_card
from vocabdeck.validation import plan_review_frontier, select_validated_curriculum
from vocabdeck.scheduling_ab import compare


def card(position, unit, sentence, *, candidate=1, context=()):
    row = audited_card()
    row.update(audit_position=position, curriculum_position=unit, candidate_position=candidate,
               sentence_id=sentence, lexeme_id=unit, lexeme_key=f"word-{unit}",
               learning_unit_key=f"unit-{unit}", difficulty_score=10.,
               context_learning_unit_keys=[f"unit-{x}" for x in {unit, *context}],
               initial_known_context_learning_unit_keys=[], lemma=f"word-{unit}")
    return row


def validation(cards, rejected=(), unreviewed=()):
    result = {"accepted": [], "rejected": [], "abstained": []}
    for c in cards:
        if c["audit_position"] in unreviewed:
            continue
        status = "rejected" if c["audit_position"] in rejected else "accepted"
        result[status].append({"audit_position": c["audit_position"], "decision": {"status": status}})
    return result


def check_order(result):
    known, sentences = set(), set()
    for c in result["accepted"]:
        assert c["sentence_id"] not in sentences
        sentences.add(c["sentence_id"])
        unknown = set(c["context_learning_unit_keys"]) - {c["learning_unit_key"]} - known
        assert unknown == set(c["scheduling"]["unknown_context_learning_unit_keys"])
        assert len(unknown) <= c["scheduling"]["unknown_allowance"]
        known.add(c["learning_unit_key"])


def test_single_reassignment_keeps_both_targets():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2), card(3, 2, 10)]
    report = validation(cards)
    greedy = select_validated_curriculum(cards, report, strategy="greedy")
    repaired = select_validated_curriculum(cards, report)
    assert len(greedy["accepted"]) == 1
    assert [c["sentence_id"] for c in repaired["accepted"]] == [11, 10]
    assert repaired["reassignment_search"]["evaluated_states"] == 1
    check_order(repaired)


@pytest.mark.parametrize("status", ["rejected", "unreviewed"])
def test_never_promotes_an_unapproved_alternative(status):
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2), card(3, 2, 10)]
    kwargs = {status: (2,)}
    result = select_validated_curriculum(cards, validation(cards, **kwargs))
    assert [c["audit_position"] for c in result["accepted"]] == [1]
    assert "sentence_reserved" in result["deferred"][0]["blockers"]


def test_failed_alternative_retries_next_approved_one():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2),
             card(3, 1, 12, candidate=3), card(4, 2, 10)]
    result = select_validated_curriculum(cards, validation(cards, rejected=(2,)))
    assert [c["audit_position"] for c in result["accepted"]] == [3, 4]


def test_replay_does_not_assume_future_words_already_known():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2, context=(2,)), card(3, 2, 10)]
    result = select_validated_curriculum(cards, validation(cards))
    assert [c["learning_unit_key"] for c in result["accepted"]] == ["unit-2", "unit-1"]
    check_order(result)


def test_two_step_reassignment_releases_dependency_sentence():
    cards = [card(1, 1, 10), card(2, 1, 20, candidate=2, context=(2,)),
             card(3, 2, 20), card(4, 2, 30, candidate=2), card(5, 3, 10)]
    report = validation(cards)
    shallow = select_validated_curriculum(cards, report, max_reassignment_depth=1)
    full = select_validated_curriculum(cards, report, max_reassignment_depth=2)
    assert len(shallow["accepted"]) == 2
    assert shallow["reassignment_search"]["depth_limit_reached"]
    assert len(full["accepted"]) == 3
    assert [c["learning_unit_key"] for c in full["accepted"]] == ["unit-2", "unit-1", "unit-3"]
    check_order(full)


def test_impossible_alternative_cannot_reduce_existing_yield():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2, context=(999,)), card(3, 2, 10)]
    result = select_validated_curriculum(cards, validation(cards))
    assert [c["audit_position"] for c in result["accepted"]] == [1]
    check_order(result)


def test_state_budget_and_zero_budget_fallback():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2), card(3, 2, 10)]
    result = select_validated_curriculum(cards, validation(cards), max_reassignment_states=0)
    assert len(result["accepted"]) == 1
    assert result["reassignment_search"]["state_limit_reached"]
    with pytest.raises(ValueError):
        select_validated_curriculum(cards, validation(cards), max_reassignment_states=1000)


def test_deterministic_and_no_search_when_requested_limit_reached():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2), card(3, 2, 10)]
    result = select_validated_curriculum(cards, validation(cards), limit=1)
    assert result["reassignment_search"]["evaluated_states"] == 0
    assert select_validated_curriculum(cards, validation(cards)) == select_validated_curriculum(cards, validation(cards))


def test_review_planner_includes_replacement_for_selected_word():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2), card(3, 2, 10)]
    report = validation(cards, unreviewed=(2,))
    selected = select_validated_curriculum(cards, report)
    frontier = plan_review_frontier(cards, selected_cards=selected["accepted"], validation_report=report)
    assert [c["audit_position"] for c in frontier["cards"]] == [2]
    assert frontier["cards"][0]["review_planning"]["purpose"] == "sentence_replacement"


def test_staged_allowance_after_twenty_preserved():
    cards = [card(i, i, i) for i in range(1, 21)]
    cards += [card(21, 21, 21, context=(22,)), card(22, 22, 22, context=(21,))]
    result = select_validated_curriculum(cards, validation(cards))
    assert len(result["accepted"]) == 22
    assert result["accepted"][20]["unknown_context_words"] == 1
    assert all(c["unknown_context_words"] == 0 for c in result["accepted"][:20])
    check_order(result)


def test_saved_evidence_ab_reports_yield_and_invariants():
    cards = [card(1, 1, 10), card(2, 1, 11, candidate=2), card(3, 2, 10)]
    result = compare(cards, validation(cards))
    assert result["yield_delta"] == 1
    assert result["removed_units"] == []
    assert result["added_units"] == ["unit-2"]
    assert result["config"]["harder_unknown_tolerance"] == 2.0
    assert all(result["runs"]["reassign"]["structural_checks"].values())
