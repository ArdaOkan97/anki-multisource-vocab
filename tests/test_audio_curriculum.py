from copy import deepcopy
import os
from unittest.mock import patch

import pytest

from vocabdeck.audio_curriculum import AudioCurriculumSession
from vocabdeck.audio_validation import ReadingAlternative, _repaired_card
from vocabdeck.constrained_review import run_constrained_curriculum
from vocabdeck.inference_resources import InferenceResourceGuard
from vocabdeck.isolated_inference import run_phase, make_audio_gate
from vocabdeck.semantic_benchmark import digest
from vocabdeck.validation import select_validated_curriculum


def card(position=1, sentence=10, candidate=1):
    return {"audit_position": position, "curriculum_position": 1, "candidate_position": candidate,
            "sentence_id": sentence, "lexeme_id": 7, "lexeme_key": "old-key",
            "candidate_key": f"old:{sentence}:2:3", "learning_unit_key": "old-unit", "sense_key": "jmdict:100:0",
            "lemma": "私", "reading": "ワタクシ", "part_of_speech": "代名詞", "gloss": "I; me",
            "japanese": "次は私だ！", "english": "I am next!", "target_surface": "私",
            "target_start": 2, "target_end": 3, "target_lexical_start": 2, "target_lexical_end": 3,
            "target_lexical_spans": [[2, 3]], "start_ms": 1000, "end_ms": 2500,
            "difficulty_score": 10., "context_learning_unit_keys": ["next-unit", "old-unit"],
            "initial_known_context_learning_unit_keys": ["next-unit"],
            "example_progression": {"content_words": 2}, "audit_findings": [],
            "audit_criteria": [{"code": code, "status": "passed"} for code in (
                "translation_available", "translation_alignment", "translation_scope", "definition_available",
                "contextual_interpretation", "gloss_support", "context_difficulty", "contextual_reading",
                "expression_interpretation", "unique_example")]}


class Gate:
    resource_policy = {"testing": "fake_no_audio_inference"}

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []

    def review(self, c, cache):
        self.calls.append(c["audit_position"])
        outcome = self.outcomes.get(c["audit_position"], "accepted")
        if outcome not in {"accepted", "repair"}:
            return {"status": "rejected", "reason": outcome, "attempts": []}
        result = deepcopy(c)
        if outcome == "repair":
            result = _repaired_card(c, ReadingAlternative("わたし", 101, 0, "I; me"), {"fixture": True})
            result["requires_contextual_revalidation"] = True
        result["start_ms"], result["end_ms"] = 1100, 2400
        result["audio_validation"] = {"status": "accepted", "repaired": outcome == "repair",
                                       "model_revision": "test_only"}
        return {"status": "accepted", "reason": outcome, "card": result}


class Reviewer:
    isolated_phases = True
    model_name = "fake-phase"

    def __init__(self, accepted=True):
        self.seen = []
        self.accepted = accepted

    def review_dataset(self, dataset, prompt_version):
        cases = dataset["splits"]["production_candidates"]
        self.seen.extend(c["card"] for c in cases)
        return {"prompt_versions": dict(dataset["prompt_versions"]), "summary": {},
                "records": [{"case_id": c["case_id"], "accepted": self.accepted,
                             "reason": "accepted" if self.accepted else "different_sense"} for c in cases]}


def accepted_validation(position=1):
    return {"accepted": [{"audit_position": position, "decision": {"status": "accepted"}}],
            "rejected": [], "abstained": []}


@pytest.mark.parametrize("failure", ["target_missing_from_audio", "competing_speech_marker", "target_near_boundary"])
def test_failed_audio_retries_next_occurrence_without_semantic_review(failure, tmp_path):
    cards = [card(), card(2, 11, 2)]
    for c in cards:
        c.update(lemma="お前", reading="オマエ", gloss="you", japanese="誰だ お前。",
                 english="Who are you?", target_surface="お前", target_start=3, target_end=5,
                 target_lexical_start=3, target_lexical_end=5, target_lexical_spans=[[3, 5]])
    gate, reviewer = Gate({1: failure}), Reviewer()
    result = run_constrained_curriculum(cards, reviewer, audio_gate=gate, audio_cache_directory=tmp_path, limit=1)
    assert gate.calls == [1, 2]
    assert [c["audit_position"] for c in reviewer.seen] == [2]
    assert result["selection"]["accepted"][0]["audit_position"] == 2
    assert result["validation"]["audio_required"]
    assert result["validation"]["rejected"][0]["decision"]["reason_codes"] == [f"audio:{failure}"]


def test_repair_precedes_fresh_semantic_review_and_updates_identity(tmp_path):
    original, gate, reviewer = card(), Gate({1: "repair"}), Reviewer()
    result = run_constrained_curriculum([original], reviewer, audio_gate=gate,
                                       audio_cache_directory=tmp_path, initial_validation=accepted_validation(), limit=1)
    c = result["selection"]["accepted"][0]
    assert reviewer.seen[0]["reading"] == "ワタシ"
    assert c["reading"] == "ワタシ" and c["learning_unit_key"] != "old-unit"
    assert c["lexeme_id"] is None and c["candidate_key"] != original["candidate_key"]
    assert set(c["context_learning_unit_keys"]) == {"next-unit", c["learning_unit_key"]}
    assert c["unknown_context_words"] == 0
    assert not c.get("requires_contextual_revalidation")
    assert c["start_ms"] == 1100
    assert original["reading"] == "ワタクシ"
    from vocabdeck.preview import render_preview_html
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"test-only")
    preview_card = {**c, "video_path": str(video), "series": "Fixture", "season": 1, "episode": 1}
    with patch("vocabdeck.preview.render_card_media", return_value={
        "image": tmp_path / "repaired.jpg", "audio": tmp_path / "repaired.mp3",
    }) as media:
        output = render_preview_html([preview_card], tmp_path / "preview.html")
    assert "<rt>わたし</rt>" in output.read_text()
    assert "<rt>わたくし</rt>" not in output.read_text()
    assert media.call_args.args[1:3] == (1100, 2400)
    assert media.call_args.args[4] == c["lexeme_key"]


def test_repair_cannot_reuse_old_semantics_when_new_review_fails(tmp_path):
    result = run_constrained_curriculum([card()], Reviewer(False), audio_gate=Gate({1: "repair"}),
                                       audio_cache_directory=tmp_path, initial_validation=accepted_validation(), limit=1)
    assert result["selection"]["accepted"] == []
    assert result["audio_state"]["records"][0]["card"]["requires_contextual_revalidation"]


def test_resume_restores_repaired_card_and_does_not_repeat_models(tmp_path):
    cards = [card()]
    first = run_constrained_curriculum(cards, Reviewer(), audio_gate=Gate({1: "repair"}),
                                      audio_cache_directory=tmp_path, limit=1)
    gate, reviewer = Gate(), Reviewer()
    second = run_constrained_curriculum(cards, reviewer, audio_gate=gate, audio_cache_directory=tmp_path,
                                       initial_validation=first["validation"], initial_audio_state=first["audio_state"],
                                       initial_predictions=first["predictions"], limit=1)
    assert not gate.calls and not reviewer.seen
    assert second["selection"]["accepted"][0]["reading"] == "ワタシ"


def test_missing_or_mismatched_resume_state_fails_closed(tmp_path):
    cards = [card()]
    first = run_constrained_curriculum(cards, Reviewer(), audio_gate=Gate(), audio_cache_directory=tmp_path, limit=1)
    with pytest.raises(ValueError, match="missing audio state"):
        AudioCurriculumSession(cards, Gate(), tmp_path, validation=first["validation"])
    altered = deepcopy(cards)
    altered[0]["reading"] = "ワタシ"
    with pytest.raises(ValueError, match="source fingerprint"):
        AudioCurriculumSession(altered, Gate(), tmp_path, state=first["audio_state"], validation=first["validation"])
    with pytest.raises(ValueError, match="validation fingerprint"):
        AudioCurriculumSession(cards, Gate(), tmp_path, state=first["audio_state"], validation={})
    with pytest.raises(ValueError, match="materialized"):
        select_validated_curriculum(cards, first["validation"])


def test_no_resident_semantic_reviewer_with_audio(tmp_path):
    reviewer = Reviewer()
    reviewer.isolated_phases = False
    with pytest.raises(ValueError, match="isolated-phase"):
        run_constrained_curriculum([card()], reviewer, audio_gate=Gate(), audio_cache_directory=tmp_path)


def test_prompt_version_two_is_propagated_to_validation(tmp_path):
    result = run_constrained_curriculum([card()], Reviewer(), audio_gate=Gate(), audio_cache_directory=tmp_path,
                                       prompt_version=2, limit=1)
    assert len(result["selection"]["accepted"]) == 1
    assert result["predictions"]["prompt_versions"]["sense"] == 2


def test_two_repaired_candidates_group_into_one_exact_unit(tmp_path):
    cards = [card(), card(2, 11, 2)]
    cards[1]["curriculum_position"] = 2
    result = run_constrained_curriculum(cards, Reviewer(), audio_gate=Gate({1: "repair", 2: "repair"}),
                                       audio_cache_directory=tmp_path, limit=2)
    assert len(result["selection"]["accepted"]) == 1
    assert len({r["card"]["learning_unit_key"] for r in result["audio_state"]["records"]}) == 1


def test_repair_updates_dependency_spans_without_global_rewrite():
    c = card()
    c.update(context_meanings_version=1, context_meaning_dependencies=[
        {"start": 0, "end": 1, "learning_unit_key": "next-unit"},
        {"start": 2, "end": 3, "learning_unit_key": "old-unit"}])
    r = _repaired_card(c, ReadingAlternative("わたし", 101, 0, "I; me"), {})
    assert r["context_meaning_dependencies"][0] == c["context_meaning_dependencies"][0]
    assert r["context_meaning_dependencies"][1]["learning_unit_key"] == r["learning_unit_key"]
    assert c["context_meaning_dependencies"][1]["learning_unit_key"] == "old-unit"


def test_media_change_invalidates_resume(tmp_path):
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"fixture")
    cards = [card()]
    cards[0]["video_path"] = str(video)
    first = run_constrained_curriculum(cards, Reviewer(), audio_gate=Gate(), audio_cache_directory=tmp_path, limit=1)
    video.write_bytes(b"changed-fixture")
    with pytest.raises(ValueError, match="media changed"):
        AudioCurriculumSession(cards, Gate(), tmp_path, state=first["audio_state"], validation=first["validation"])


def test_real_child_probe_exits_without_loading_model():
    result = run_phase({"kind": "probe"}, timeout_seconds=30)
    assert result["probe"] == "no_model_loaded"
    assert result["runtime"]["pid"] != os.getpid()
    assert result["runtime"]["process_exit_verified"]
    with InferenceResourceGuard():
        pass


def test_child_fails_when_inference_lock_is_held():
    with InferenceResourceGuard():
        with pytest.raises(RuntimeError, match="failed"):
            run_phase({"kind": "probe"}, timeout_seconds=30)


def test_resource_limits_cannot_be_raised():
    with pytest.raises(ValueError, match="ceiling"):
        run_phase({"kind": "probe"}, memory_limit_gb=30)
    with pytest.raises(ValueError, match="ceiling"):
        make_audio_gate(30)


def test_mocked_ab_replaces_bad_clip_instead_of_losing_word(tmp_path):
    cards = [card(), card(2, 11, 2)]
    text_only = run_constrained_curriculum(cards, Reviewer(), limit=1)
    gated = run_constrained_curriculum(cards, Reviewer(), audio_gate=Gate({1: "target_missing_from_audio"}),
                                      audio_cache_directory=tmp_path, limit=1)
    assert [c["audit_position"] for c in text_only["selection"]["accepted"]] == [1]
    assert [c["audit_position"] for c in gated["selection"]["accepted"]] == [2]
    assert len(text_only["selection"]["accepted"]) == len(gated["selection"]["accepted"]) == 1


def test_resume_rejects_changed_gate_policy_and_corrupt_records(tmp_path):
    cards = [card()]
    first = run_constrained_curriculum(cards, Reviewer(), audio_gate=Gate(), audio_cache_directory=tmp_path, limit=1)
    altered_gate = Gate()
    altered_gate.resource_policy = {"different": True}
    with pytest.raises(ValueError, match="gate configuration"):
        AudioCurriculumSession(cards, altered_gate, tmp_path, state=first["audio_state"], validation=first["validation"])
    altered_state = deepcopy(first["audio_state"])
    altered_state["records"][0]["card"]["reading"] = "ワタシ"
    with pytest.raises(ValueError, match="record fingerprint"):
        AudioCurriculumSession(cards, Gate(), tmp_path, state=altered_state, validation=first["validation"])
