from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vocabdeck.embedding_calibration import (
    build_pool, choose_threshold, evaluate, metrics, stratum, validate_pairs,
)
from vocabdeck.embedding_pair_probe import make_pairs
from vocabdeck.semantic_benchmark import digest


def example():
    pairs = [{"case_id": str(i), "word": f"word{i}", "reading": "a",
              "definitions": [f"left{i}", f"right{i}"], "sense_keys": ["a", "b"],
              "pilot": True, "split": split, "gold": None}
             for i, split in enumerate(["calibration", "calibration", "heldout", "heldout"])]
    data = {"pairs": pairs, "pairs_hash": digest(pairs)}
    labels = {"annotator": "test-model", "label_provenance": "model_draft_not_human_gold",
              "pairs_hash": data["pairs_hash"],
              "labels": [{"case_id": str(i), "label": label, "reason": "fixture"}
                         for i, label in enumerate(["equivalent", "distinct", "equivalent", "distinct"])]}
    report = {"model": "test", "pairs_hash": data["pairs_hash"],
              "records": [{**pair, "cosine": score} for pair, score in zip(pairs, [.9, .8, .92, .95])]}
    return data, labels, report


def test_heldout_false_merge_does_not_recalibrate_threshold():
    data, labels, report = example()
    result = evaluate(data, labels, [report])
    assert result["results"][0]["experimental_threshold"] == .9
    assert result["results"][0]["calibration"]["false_merges"] == 0
    assert result["results"][0]["heldout"]["false_merges"] == 1
    assert result["gold_scored"] == 0 and result["production_ready"] is False
    report["records"][3]["cosine"] = .1
    assert evaluate(data, labels, [report])["results"][0]["experimental_threshold"] == .9


def test_uncertain_not_silently_a_positive_or_omitted():
    records = [{"label": "equivalent", "cosine": .8}, {"label": "uncertain", "cosine": .9}]
    assert choose_threshold(records) is None
    assert metrics(records, .8)["uncertain_accepted"] == 1
    assert metrics(records, None)["accepted"] == 0


def test_tied_scores_cannot_be_separated():
    records = [{"label": "equivalent", "cosine": .9}, {"label": "distinct", "cosine": .9}]
    assert choose_threshold(records) is None


def test_maximum_safe_calibration_coverage():
    records = [{"label": label, "cosine": score} for label, score in
               [("equivalent", .95), ("equivalent", .9), ("distinct", .8)]]
    assert choose_threshold(records) == .9
    assert metrics(records, .9)["provisional_wilson_lower_95"] < .5


@pytest.mark.parametrize("mutation", ["hash", "duplicate", "leak", "gold"])
def test_invalid_pair_sets_rejected(mutation):
    data, _, _ = example()
    if mutation == "hash":
        data["pairs_hash"] = "wrong"
    elif mutation == "duplicate":
        data["pairs"][1]["definitions"] = list(reversed(data["pairs"][0]["definitions"]))
    elif mutation == "leak":
        data["pairs"][2]["word"] = data["pairs"][0]["word"]
    else:
        data["pairs"][0]["gold"] = "equivalent"
    if mutation != "hash":
        data["pairs_hash"] = digest(data["pairs"])
    with pytest.raises(ValueError):
        validate_pairs(data)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "provenance", "hash", "bad_label", "missing_score", "nan", "changed_input"])
def test_annotation_and_score_integrity(mutation):
    data, labels, report = example()
    if mutation == "missing":
        labels["labels"].pop()
    elif mutation == "duplicate":
        labels["labels"].append(deepcopy(labels["labels"][0]))
    elif mutation == "provenance":
        labels["label_provenance"] = "human_gold"
    elif mutation == "hash":
        labels["pairs_hash"] = "other"
    elif mutation == "bad_label":
        labels["labels"][0]["label"] = "maybe"
    elif mutation == "missing_score":
        report["records"].pop()
    elif mutation == "nan":
        report["records"][0]["cosine"] = float("nan")
    else:
        report["records"][0]["definitions"] = ["changed", "input"]
    with pytest.raises(ValueError):
        evaluate(data, labels, [report])


def test_external_pairs_survive_unchanged_into_embedding_probe():
    data, _, _ = example()
    assert make_pairs(data) == data["pairs"]


def test_metadata_review_requires_frozen_evidence():
    data, labels, report = example()
    evidence = {"pairs_hash": data["pairs_hash"], "evidence": [{"field": "physics"}]}
    evidence["evidence_hash"] = digest(evidence["evidence"])
    labels["evidence_hash"] = evidence["evidence_hash"]
    with pytest.raises(ValueError, match="evidence"):
        evaluate(data, labels, [report])
    assert evaluate(data, labels, [report], evidence)["gold_scored"] == 0
    evidence["evidence"][0]["field"] = "changed"
    with pytest.raises(ValueError, match="evidence"):
        evaluate(data, labels, [report], evidence)


def test_deterministic_build_without_embeddings_or_labels():
    class Resolver:
        def sense_candidates(self, word, *args):
            i = int(word[1:])
            return [SimpleNamespace(entry_id=i, sense_index=n, gloss=f"{word} meaning {n}")
                    for n in range(3)]
    cards = [{"lemma": f"w{i}", "reading": "a"} for i in range(30)]
    a = build_pool(cards, Resolver(), limit=40, pilot_size=10)
    b = build_pool(cards[::-1], Resolver(), limit=40, pilot_size=10)
    assert a["pairs"] == b["pairs"]
    assert len(a["pairs"]) == 40
    assert len({p["word"] for p in a["pairs"] if p["pilot"]}) == 10
    validate_pairs(a)


def test_pool_does_not_fill_with_invented_or_identical_examples():
    class Resolver:
        def sense_candidates(self, *args):
            return [SimpleNamespace(entry_id=1, sense_index=n, gloss="same") for n in range(3)]
    with pytest.raises(ValueError, match="only 0"):
        build_pool([{"lemma": "a", "reading": "a"}], Resolver(), limit=1, pilot_size=1)


def test_overlap_strata():
    assert stratum(["to start", "to begin"]) == "no_overlap"
    assert stratum(["to start", "to start something"]) == "high_overlap"


def test_checked_in_pilot_provenance_and_integrity():
    folder = Path(__file__).resolve().parents[1] / "benchmarks/verifier-gold-v1"
    read = lambda name: json.loads((folder / f"dictionary-calibration-{name}.json").read_text())
    dataset = read("pool-v1")
    pairs = validate_pairs(dataset)
    assert len(pairs) == 1000
    pilot_ids = {p["case_id"] for p in pairs if p["pilot"]}
    assert len(pilot_ids) == 100
    evidence = read("pilot-evidence")
    for name in ("pilot-labels", "pilot-reviewed-labels"):
        labels = read(name)
        assert labels["pairs_hash"] == dataset["pairs_hash"]
        assert labels["label_provenance"] == "model_draft_not_human_gold"
        assert len(labels["labels"]) == 100
        assert {r["case_id"] for r in labels["labels"]} == pilot_ids
    assert labels["evidence_hash"] == digest(evidence["evidence"])
    result = read("pilot-results")
    assert result["annotations_hash"] == digest(labels)
    assert result["dataset_hash"] == dataset["pairs_hash"]
    assert result["production_ready"] is False
