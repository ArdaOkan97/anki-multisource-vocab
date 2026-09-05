from copy import deepcopy

import pytest

from test_validation import audited_card
from vocabdeck.candidate_accounting import (
    build_candidate_accounting, render_candidate_accounting,
)
from vocabdeck.validation import plan_review_frontier


def candidate(position, unit, sentence=None, context=(), difficulty=10):
    return dict(
        audited_card(), audit_position=position, curriculum_position=position,
        learning_unit_key=unit, candidate_key=f"candidate-{position}",
        sentence_id=position if sentence is None else sentence,
        context_learning_unit_keys=[unit, *context],
        initial_known_context_learning_unit_keys=[], difficulty_score=difficulty,
    )


def validation(*pairs):
    report = {"accepted": [], "rejected": [], "abstained": []}
    for card, status in pairs:
        report[status].append({
            "audit_position": card["audit_position"], "lexeme_key": card["lexeme_key"],
            "decision": {"status": status, "stages": [{
                "validator": "llm:constrained_verifier", "status": status,
                "reason_codes": [] if status == "accepted" else ["test_reason"],
            }]},
        })
    return report


def selection(*cards, zero=20):
    return {"accepted": list(cards), "summary": {"zero_unknown_through": zero}}


def test_reconciles_and_distinguishes_model_outcomes_from_reservations():
    taught = candidate(1, "you", sentence=10)
    alternative = candidate(2, "you")
    shared = candidate(3, "who", sentence=10)
    untouched = candidate(4, "who", context=["you"])
    bad = candidate(5, "bad")
    abstain = candidate(6, "uncertain")
    cards = [taught, alternative, shared, untouched, bad, abstain]
    report = build_candidate_accounting(
        cards, validation((taught, "accepted"), (shared, "accepted"),
                          (bad, "rejected"), (abstain, "abstained")),
        selection(taught), harder_unknown_tolerance=None,
    )
    assert report["summary"]["primary_counts_reconcile"]
    assert report["summary"]["candidate_pairs"] == 6
    assert report["summary"]["distinct_sentences"] == 5
    assert report["summary"]["learning_units"] == 4
    assert [r["primary_disposition"] for r in report["candidates"]] == [
        "selected", "alternative_to_selected_target", "sentence_reserved",
        "eligible_unreviewed", "validation_rejected", "validation_abstained",
    ]
    row = report["candidates"][2]
    assert row["model_review_status"] == "accepted"
    assert row["sentence_reserved_by"]["learning_unit_key"] == "you"
    assert report["candidates"][3]["final_state"]["unknown_context_words"] == 0
    assert report["summary"]["model_review_counts"]["not_reviewed"] == 2


def test_all_independent_blockers_survive_primary_precedence():
    taught = candidate(1, "taught")
    blocked = candidate(2, "blocked", sentence=1, context=["unscored", "hard"])
    hard = candidate(3, "hard", difficulty=30)
    report = build_candidate_accounting(
        [taught, blocked, hard], validation((taught, "accepted")),
        selection(taught), harder_unknown_tolerance=2,
    )
    row = report["candidates"][1]
    assert row["primary_disposition"] == "sentence_reserved"
    assert row["final_state"]["blockers"] == [
        "sentence_reserved", "unknown_context_limit", "unscored_unknown_context",
        "harder_unknown_context",
    ]
    assert row["model_review_status"] == "not_reviewed"


def test_missing_metadata_is_not_zero_unknown_and_null_translation_is_renderable(tmp_path):
    missing = candidate(1, "missing")
    del missing["context_learning_unit_keys"]
    no_translation = dict(candidate(2, "bad"), english=None)
    report = build_candidate_accounting(
        [missing, no_translation], validation(), selection(), harder_unknown_tolerance=None,
    )
    assert report["candidates"][0]["primary_disposition"] == "missing_context_metadata"
    assert report["candidates"][0]["final_state"]["unknown_context_words"] is None
    assert report["candidates"][1]["primary_disposition"] == "deterministic_rejected"
    assert report["candidates"][1]["model_review_status"] == "not_reviewed"
    assert render_candidate_accounting(report, tmp_path / "report.html").exists()


@pytest.mark.parametrize("tolerance", [None, 2.0])
@pytest.mark.parametrize("zero,selected_count", [(20, 0), (20, 20), (0, 200)])
def test_diagnostics_match_review_planner_eligibility(tolerance, zero, selected_count):
    taught = [candidate(i + 1, f"known-{i}") for i in range(selected_count)]
    offset = selected_count + 1
    easy = candidate(offset, "easy", context=["hard"])
    hard = candidate(offset + 1, "hard", difficulty=40)
    too_many = candidate(offset + 2, "many", context=["easy", "hard", "absent"])
    unscored = candidate(offset + 3, "unscored", context=["absent"])
    cards = [*taught, easy, hard, too_many, unscored]
    decisions = validation(*[(card, "accepted") for card in taught])
    report = build_candidate_accounting(
        cards, decisions, selection(*taught, zero=zero), harder_unknown_tolerance=tolerance,
    )
    planned = plan_review_frontier(
        cards, selected_cards=taught, validation_report=decisions, limit=1000,
        zero_unknown_through=zero, harder_unknown_tolerance=tolerance,
    )
    assert {r["audit_position"] for r in report["candidates"]
            if r["primary_disposition"] == "eligible_unreviewed"} == {
        c["audit_position"] for c in planned["cards"]
    }


def test_legacy_validation_does_not_fabricate_model_review():
    card = candidate(1, "unit")
    decisions = validation((card, "accepted"))
    del decisions["accepted"][0]["decision"]["stages"]
    report = build_candidate_accounting([card], decisions, selection(), harder_unknown_tolerance=None)
    assert report["candidates"][0]["model_review_status"] == "provenance_unavailable"
    assert report["candidates"][0]["primary_disposition"] == "accepted_not_selected"


def test_inconsistent_inputs_fail_closed():
    card = candidate(1, "unit")
    with pytest.raises(ValueError, match="duplicate candidate"):
        build_candidate_accounting([card, card], validation(), selection(), harder_unknown_tolerance=None)
    with pytest.raises(ValueError, match="unknown or duplicate validation"):
        build_candidate_accounting([], validation((card, "accepted")), selection(), harder_unknown_tolerance=None)
    changed = dict(card, english="Changed after review")
    with pytest.raises(ValueError, match="selected occurrence mismatch"):
        build_candidate_accounting([card], validation((card, "accepted")), selection(changed), harder_unknown_tolerance=None)
    with pytest.raises(ValueError, match="no accepted validation"):
        build_candidate_accounting([card], validation(), selection(card), harder_unknown_tolerance=None)
    with pytest.raises(ValueError, match="selection repeats"):
        build_candidate_accounting([card], validation((card, "accepted")), selection(card, card), harder_unknown_tolerance=None)
    for invalid in [-1, float("nan"), float("inf")]:
        with pytest.raises(ValueError, match="nonnegative"):
            build_candidate_accounting([], validation(), selection(), harder_unknown_tolerance=invalid)


def test_report_is_read_only_and_html_escapes_untrusted_text(tmp_path):
    card = candidate(1, "<script>alert(1)</script>")
    card["english"] = "<img src=x onerror=alert(1)>"
    inputs = ([card], validation(), selection())
    before = deepcopy(inputs)
    report = build_candidate_accounting(*inputs, harder_unknown_tolerance=None)
    assert inputs == before
    rendered = render_candidate_accounting(report, tmp_path / "report.html").read_text()
    assert "<img src=x" not in rendered
    assert "<script>alert(1)" not in rendered
    assert "&lt;img src=x" in rendered


def test_cli_writes_hashed_report_without_modifying_inputs(tmp_path, capsys):
    import hashlib
    import json
    from vocabdeck.cli import main

    card = candidate(1, "unit")
    inputs = [tmp_path / name for name in ("cards.json", "validation.json", "selection.json")]
    documents = [{"cards": [card]}, validation(), selection()]
    for path, document in zip(inputs, documents):
        path.write_text(json.dumps(document), encoding="utf-8")
    before = [path.read_bytes() for path in inputs]
    output, html = tmp_path / "accounting.json", tmp_path / "accounting.html"
    args = [
        "explain-curriculum-candidates", "--input", str(inputs[0]),
        "--validation", str(inputs[1]), "--selection", str(inputs[2]),
        "--harder-unknown-tolerance", "none", "--json-output", str(output),
        "--html-output", str(html),
    ]
    assert main(args) == 0
    assert [path.read_bytes() for path in inputs] == before
    report = json.loads(output.read_text())
    assert report["sources"]["candidates"]["sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert json.loads(capsys.readouterr().out)["candidate_pairs"] == 1
    assert "eligible_unreviewed" in html.read_text()
    args[args.index("--json-output") + 1] = str(inputs[0])
    with pytest.raises(ValueError, match="overwrite input"):
        main(args)
    assert inputs[0].read_bytes() == before[0]
