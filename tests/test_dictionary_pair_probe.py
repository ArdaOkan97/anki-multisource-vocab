from copy import deepcopy

import pytest

from vocabdeck.dictionary_pair_probe import build_pairs, build_prompt, run_probe
from vocabdeck.semantic_benchmark import make_case


def source():
    def occurrence(sentence):
        return {"card": {"lemma": "あれ", "reading": "アレ", "japanese": sentence,
                         "target_surface": "あれ", "target_start": 0, "target_end": 2,
                         "sense_key": "one"},
                "options": [{"sense_key": "one", "gloss": "that; that thing"}]}
    case = make_case("equivalence", {"left": occurrence("あれだ"), "right": occurrence("あれ？")},
                     "development", "synthetic test fixture")
    return {"schema_version": 1, "cases": [case]}


def pair():
    return build_pairs(source())[0]


def test_only_word_and_two_glosses_reach_prompt():
    p = build_prompt(pair(), 0)
    assert "Word: あれ" in p.prompt
    assert "Meaning 1: that; that thing" in p.prompt
    assert "あれだ" not in p.prompt
    assert "あれ？" not in p.prompt
    assert "sense_key" not in p.prompt
    assert "target_start" not in p.prompt
    assert p.prompt.endswith("Answer with one letter.")


def test_both_meaning_order_and_choices_rotate():
    p = pair()
    p["meanings"][1]["gloss"] = "huh?"
    assert "Meaning 1: huh?" in build_prompt(p, 1).prompt
    assert build_prompt(p, 0).label_to_sense["A"] == "same"
    assert build_prompt(p, 1).label_to_sense["A"] == "different"
    assert build_prompt(p, 1).label_to_sense["C"] == "same"


def test_controls_not_gold_and_input_not_modified():
    data = source()
    before = deepcopy(data)
    pairs = build_pairs(data)
    assert data == before
    assert len(pairs) == 2
    assert pairs[1]["kind"] == "identical_gloss_control"
    assert pairs[1]["meanings"][0] == pairs[1]["meanings"][1]
    assert pairs[0]["case_id"] != pairs[1]["case_id"]
    assert all(p["gold"] is None for p in pairs)


@pytest.mark.parametrize("answers,relation,reason", [
    (["B", "A"], "different", "stable"),
    (["A", "C"], "same", "stable"),
    (["C", "B"], None, "uncertain"),
    (["A", "A"], None, "order_disagreement"),
    (["B. Different", "A"], None, "invalid_output"),
    ([], None, "invalid_output"),
])
def test_identical_strict_parser(answers, relation, reason):
    class Reviewer:
        model_name = "synthetic"

        def review(self, prompts):
            assert len(prompts) == 2
            return answers, {"peak_memory": 1.0}
    saved = []
    report = run_probe([pair()], Reviewer(), checkpoint=lambda r: saved.append(deepcopy(r)))
    assert report["records"][0]["relation"] == relation
    assert report["records"][0]["reason"] == reason
    assert report["summary"]["gold_scored"] == 0
    assert report["summary"]["prompt_calls"] == 2
    assert len(saved) == 1
