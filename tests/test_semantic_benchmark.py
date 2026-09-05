from copy import deepcopy
import json

import pytest

from vocabdeck.semantic_benchmark import (
    build_prompt, build_queue, case_fingerprint, evaluate, make_case,
    occurrence, run_dataset, validate_dataset,
)


def item(initial="old", japanese="例文"):
    return {"card": {"lemma": "例", "reading": "レイ", "japanese": japanese,
                     "english": "An example", "sense_key": initial,
                     "target_surface": "例", "target_start": 0, "target_end": 1},
            "options": [{"sense_key": "old", "gloss": "old meaning"},
                        {"sense_key": "new", "gloss": "new meaning"}]}


def case(task="sense"):
    inputs = item() if task == "sense" else {"left": item(), "right": item(japanese="例です")}
    return make_case(task, inputs, "development", "synthetic unit-test fixture")


def dataset(*cases):
    return {"schema_version": 1, "dataset_id": "test", "cases": list(cases)}


def reviewed(value, gold):
    value = deepcopy(value)
    value.update(review_status="reviewed", gold=gold, provenance={
        "kind": "explicit_human_semantic_review", "reviewer": "test-fixture",
        "note": "Synthetic schema fixture, never empirical model accuracy evidence.",
    })
    return value


class FakeReviewer:
    model_name = "synthetic-test"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def review(self, prompts):
        self.calls += len(prompts)
        return next(self.responses), {"peak_memory": 0.25}


def answers(value, selected, *, gloss=None):
    return [next(label for label, meaning in build_prompt(
        value, round_index, gloss=gloss
    ).label_to_sense.items() if meaning == selected) for round_index in range(2)]


def test_correction_is_recorded_and_support_uses_new_gloss():
    value = case()
    reviewer = FakeReviewer([answers(value, "new"), answers(value, "expressed", gloss="new meaning")])
    before = deepcopy(value)
    report = run_dataset(dataset(value), reviewer)
    row = report["records"][0]
    assert row["decision"] == "repair"
    assert row["selected_sense_key"] == "new"
    assert row["proposed_correction"]
    assert "new meaning" in row["attempts"][1]["prompts"][0]
    assert "old meaning" not in row["attempts"][1]["prompts"][0]
    assert value == before
    assert report["summary"]["prompt_calls"] == 4


def test_wrong_subtitle_blocks_even_a_stable_corrected_sense():
    value = case()
    reviewer = FakeReviewer([answers(value, "new"), answers(value, "not_expressed", gloss="new meaning")])
    row = run_dataset(dataset(value), reviewer)["records"][0]
    assert row["decision"] == "reject"
    assert row["selected_sense_key"] == "new"


@pytest.mark.parametrize("raw,reason", [(["A", "A"], "order_disagreement"),
                                        (["A", "Explanation"], "invalid_output"),
                                        ([], "invalid_output")])
def test_fail_closed(raw, reason):
    row = run_dataset(dataset(case()), FakeReviewer([raw]))["records"][0]
    assert row["decision"] == "abstain"
    assert row["reason"] == reason
    assert len(row["attempts"]) == 1


def test_uncertainty_rotates_even_with_one_option():
    value = case()
    value["input"]["options"] = value["input"]["options"][:1]
    assert build_prompt(value, 0).label_to_sense != build_prompt(value, 1).label_to_sense
    assert answers(value, None) == ["B", "A"]


def test_equivalence_swaps_context_and_labels_and_excludes_initial_gloss():
    value = case("equivalence")
    value["input"]["left"]["card"]["gloss"] = "LEAKED-GUESS"
    left = build_prompt(value, 0)
    right = build_prompt(value, 1)
    first_data = json.loads(left.prompt.splitlines()[3])
    second_data = json.loads(right.prompt.splitlines()[3])
    assert first_data == list(reversed(second_data))
    assert left.label_to_sense != right.label_to_sense
    assert "LEAKED-GUESS" not in left.prompt


def test_false_repairs_and_false_merges_count_not_just_abstentions():
    repair = reviewed(case(), {"acceptable_sense_keys": ["old"], "subtitle_support": "expressed"})
    pair = reviewed(case("equivalence"), {"relation": "different"})
    data = dataset(repair, pair)
    reviewer = FakeReviewer([answers(repair, "new"), answers(repair, "expressed", gloss="new meaning"),
                             answers(pair, "same")])
    report = evaluate(data, run_dataset(data, reviewer))
    counts = report["splits"]["development"]
    assert counts["false_repairs"] == counts["false_merges"] == counts["false_accepts"] == 1
    assert counts["valid_card_coverage"] == 0
    assert counts["retained_distinctions"] == 0
    assert report["production_ready"] is False


def test_good_repair_and_equivalence_recall():
    repair = reviewed(case(), {"acceptable_sense_keys": ["new"], "subtitle_support": "expressed"})
    pair = reviewed(case("equivalence"), {"relation": "same"})
    data = dataset(repair, pair)
    reviewer = FakeReviewer([answers(repair, "new"), answers(repair, "expressed", gloss="new meaning"),
                             answers(pair, "same")])
    counts = evaluate(data, run_dataset(data, reviewer))["splits"]["development"]
    assert counts["false_repairs"] == counts["false_merges"] == 0
    assert counts["valid_card_coverage"] == counts["equivalence_recall"] == 1


def test_unreviewed_not_scored_and_empty_heldout_visible():
    value = case()
    heldout = make_case("sense", item(japanese="例か"), "second_show", "fixture")
    data = dataset(value, heldout)
    report = run_dataset(data, FakeReviewer([answers(value, None)]), limit=1)
    scores = evaluate(data, report)["splits"]
    assert scores["development"]["unscored_predictions"] == 1
    assert "scored" not in scores["development"]
    assert scores["second_show"]["unreviewed_cases"] == 1
    assert scores["second_show"]["valid_card_coverage"] is None


def test_implicit_pass_and_assistant_review_are_not_gold():
    value = reviewed(case(), {"acceptable_sense_keys": ["old"], "subtitle_support": "expressed"})
    for kind in ("human_review", "llm_review", "assistant_proposal"):
        value["provenance"]["kind"] = kind
        with pytest.raises(ValueError, match="explicit human"):
            validate_dataset(dataset(value))


def test_input_changes_invalidate_identity_but_labels_do_not():
    value = case()
    annotated = reviewed(value, {"acceptable_sense_keys": ["old"], "subtitle_support": "expressed"})
    assert case_fingerprint(annotated) == case_fingerprint(value)
    value["input"]["options"][0]["gloss"] = "changed"
    with pytest.raises(ValueError, match="frozen input"):
        validate_dataset(dataset(value))


def test_stale_and_duplicate_predictions_refused():
    value = case()
    data = dataset(value)
    report = run_dataset(data, FakeReviewer([answers(value, None)]))
    report["records"].append(deepcopy(report["records"][0]))
    with pytest.raises(ValueError, match="stale prediction"):
        evaluate(data, report)
    report["records"].pop()
    report["records"][0]["input_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="stale prediction"):
        evaluate(data, report)


def test_missing_options_no_inference():
    value = make_case("sense", {**item(), "options": []}, "development", "fixture")
    reviewer = FakeReviewer([])
    row = run_dataset(dataset(value), reviewer)["records"][0]
    assert reviewer.calls == 0
    assert row["reason"] == "missing_or_too_many_options"


def test_candidate_lookup_ignores_old_pos_and_construction():
    class Resolver:
        def sense_candidates(self, *args):
            assert args == ("例", "レイ", "", "", None)
            return ()
    card = {**item()["card"], "part_of_speech": "名詞"}
    assert occurrence(card, Resolver())["options"] == []


def test_queue_does_not_import_old_labels():
    class Resolver:
        def sense_candidates(self, *args):
            return ()
    cards = [item()["card"], item(japanese="例です")["card"]]
    old = {"splits": {"development": [{"card": cards[0], "case_id": "old-gold",
                                        "review_status": "gold", "labels": {"sense": "expected"}}]}}
    queue = build_queue(cards, old, Resolver())
    assert len(queue["cases"]) == 2
    assert all(case["gold"] is None and case["review_status"] == "unreviewed" for case in queue["cases"])


def test_equivalence_cannot_compare_different_readings():
    value = case("equivalence")
    value["input"]["right"]["card"]["reading"] = "ベツ"
    value = make_case("equivalence", value["input"], "development", "fixture")
    with pytest.raises(ValueError, match="same lemma and reading"):
        validate_dataset(dataset(value))


def test_duplicate_source_inputs_not_counted_twice():
    class Resolver:
        def sense_candidates(self, *args):
            return ()
    old = {"splits": {"second_show": [
        {"card": item()["card"], "case_id": "source-1"},
        {"card": item()["card"], "case_id": "source-2"},
    ]}}
    queue = build_queue([], old, Resolver())
    assert len(queue["cases"]) == 1
    assert queue["cases"][0]["provenance"]["duplicate_sources"] == ["source-2"]
    old["splits"]["development"] = old["splits"]["second_show"][:1]
    with pytest.raises(ValueError, match="different splits"):
        build_queue([], old, Resolver())


def test_gold_must_be_in_dictionary_options_and_empty_means_no_supported_choice():
    value = reviewed(case(), {"acceptable_sense_keys": [], "subtitle_support": "uncertain"})
    validate_dataset(dataset(value))
    value["gold"]["acceptable_sense_keys"] = ["made-up"]
    with pytest.raises(ValueError, match="frozen dictionary options"):
        validate_dataset(dataset(value))


def test_predictions_cannot_invent_repair_definition():
    value = case()
    data = dataset(value)
    report = run_dataset(data, FakeReviewer([answers(value, None)]))
    report["records"][0]["selected_sense_key"] = "invented"
    with pytest.raises(ValueError, match="outside dictionary"):
        evaluate(data, report)


def test_checkpoint_and_limit():
    a, b = case(), case("equivalence")
    saved = []
    report = run_dataset(dataset(a, b), FakeReviewer([answers(a, None)]),
                         limit=1, checkpoint=lambda p: saved.append(deepcopy(p)))
    assert len(saved) == 1
    assert len(report["records"]) == 1
    with pytest.raises(ValueError, match="positive"):
        run_dataset(dataset(a), FakeReviewer([]), limit=0)


def test_bad_target_span_refused():
    value = item()
    value["card"]["target_end"] = 20
    with pytest.raises(ValueError, match="target span"):
        validate_dataset(dataset(make_case("sense", value, "development", "fixture")))


def test_cli_passes_memory_guard_settings_and_closes_on_error(tmp_path, monkeypatch):
    import vocabdeck.constrained_review as constrained
    from vocabdeck.semantic_benchmark import main

    calls = []

    class FakeMLX:
        model_name = "fake"

        def __init__(self, model, **kwargs):
            calls.append((model, kwargs))

        def review(self, prompts):
            raise RuntimeError("simulated inference failure")

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(constrained, "MLXLabelReviewer", FakeMLX)
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset(case())))
    with pytest.raises(RuntimeError, match="simulated inference"):
        main(["run", "--dataset", str(path), "--model", "fake", "--revision", "pinned",
              "--memory-limit-gb", "4", "--output", str(tmp_path / "out.json")])
    assert calls == [("fake", {"revision": "pinned", "memory_limit_gb": 4.0}), "closed"]
