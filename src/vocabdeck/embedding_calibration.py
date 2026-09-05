"""Reproducible dictionary-pair pilot; machine labels are never benchmark gold."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import combinations, zip_longest
import json
import math
from pathlib import Path
import re

from .constrained_review import sense_options
from .dictionary import JMDictResolver
from .semantic_benchmark import digest, _write

SEED = "dictionary-calibration-pilot-v1"
# Already inspected examples belong to diagnostics, not a fresh test set.
PREVIOUSLY_SEEN = {"何", "あれ", "分かる", "こっち", "どっち", "くれる"}
LABELS = {"equivalent", "distinct", "uncertain"}


def normalized(text):
    return " ".join(text.casefold().split())


def definition_key(pair):
    return tuple(sorted(normalized(x) for x in pair["definitions"]))


def stratum(definitions):
    a, b = [set(re.findall(r"[a-z]+", text.lower())) - {"to", "the", "a", "an", "of"}
            for text in definitions]
    overlap = len(a & b) / max(1, len(a | b))
    return "high_overlap" if overlap >= .3 else "some_overlap" if overlap else "no_overlap"


def build_pool(cards, resolver=None, limit=1000, pilot_size=100):
    if limit < 1 or not 0 < pilot_size <= limit:
        raise ValueError("invalid pool/pilot size")
    resolver = resolver or JMDictResolver()
    by_word = defaultdict(list)
    for word, reading in sorted({(c["lemma"], c["reading"]) for c in cards}):
        options = sense_options({"lemma": word, "reading": reading}, resolver)
        for left, right in combinations(options, 2):
            definitions = [left["gloss"], right["gloss"]]
            if normalized(definitions[0]) == normalized(definitions[1]):
                continue  # Identity controls must not inflate calibration precision.
            pair = {"word": word, "reading": reading, "definitions": definitions,
                    "sense_keys": [left["sense_key"], right["sense_key"]],
                    "kind": "real_dictionary_pair", "gold": None}
            pair["case_id"] = digest(pair)[:24]
            pair["stratum"] = stratum(definitions)
            by_word[word].append(pair)
    # Round robin words before taking additional senses from the same word.
    groups = [sorted(v, key=lambda p: digest([SEED, p["case_id"]]))
              for _, v in sorted(by_word.items(), key=lambda kv: digest([SEED, kv[0]]))]
    selected, seen = [], set()
    for row in zip_longest(*groups):
        for pair in row:
            if pair is None or definition_key(pair) in seen:
                continue
            seen.add(definition_key(pair))
            selected.append(pair)
            if len(selected) == limit:
                break
        if len(selected) == limit:
            break
    if len(selected) < limit:
        raise ValueError(f"only {len(selected)} unique real pairs available; requested {limit}")
    # Balanced lexical-overlap strata, without accessing embeddings or labels.
    buckets = defaultdict(list)
    for pair in selected:
        if pair["word"] not in PREVIOUSLY_SEEN:
            buckets[pair["stratum"]].append(pair)
    pilot_ids, words = set(), set()
    for row in zip_longest(*(buckets[k] for k in sorted(buckets))):
        for pair in row:
            if pair and pair["word"] not in words:
                words.add(pair["word"])
                pilot_ids.add(pair["case_id"])
                if len(pilot_ids) == pilot_size:
                    break
        if len(pilot_ids) == pilot_size:
            break
    if len(pilot_ids) != pilot_size:
        raise ValueError("not enough distinct fresh words for pilot")
    for pair in selected:
        pair["split"] = ("diagnostic" if pair["word"] in PREVIOUSLY_SEEN else
                         "calibration" if int(digest([SEED, pair["word"]])[:8], 16) % 10 < 7
                         else "heldout")
        pair["pilot"] = pair["case_id"] in pilot_ids
    return {"schema_version": 1, "dataset_id": SEED, "seed": SEED,
            "source_cards_hash": digest(cards), "pairs": selected,
            "pairs_hash": digest(selected), "gold_scored": 0,
            "selection": "word round-robin; pilot overlap-stratified, one pair per fresh word"}


def validate_pairs(dataset):
    pairs = dataset["pairs"]
    if not pairs or dataset["pairs_hash"] != digest(pairs):
        raise ValueError("pair fingerprint mismatch")
    ids, definitions, splits = set(), set(), {}
    for pair in pairs:
        if pair["case_id"] in ids or definition_key(pair) in definitions:
            raise ValueError("duplicate pair")
        ids.add(pair["case_id"])
        definitions.add(definition_key(pair))
        if pair["split"] not in {"calibration", "heldout", "diagnostic"}:
            raise ValueError("invalid split")
        if splits.setdefault(pair["word"], pair["split"]) != pair["split"]:
            raise ValueError("word leakage across splits")
        if pair.get("gold") is not None:
            raise ValueError("machine pilot must not assert gold")
    return pairs


def source_evidence(dataset, resolver=None):
    """Retain omitted dictionary qualifiers for score-blind annotation review."""
    resolver = resolver or JMDictResolver()
    rows = []
    for pair in validate_pairs(dataset):
        if not pair["pilot"]:
            continue
        entries = {int(e.idseq): e for e in resolver.dictionary.lookup(
            pair["word"], lookup_chars=False, lookup_ne=False).entries}
        meanings = []
        for key in pair["sense_keys"]:
            _, entry, index = key.split(":")
            sense = entries[int(entry)].senses[int(index)]
            meanings.append({"sense_key": key,
                             "full_english_glosses": [g.text for g in sense.gloss if g.lang in ("", "eng")],
                             **{field: [str(x) for x in getattr(sense, field)]
                                for field in ("pos", "field", "misc", "info", "stagk", "stagr")}})
        rows.append({"case_id": pair["case_id"], "word": pair["word"],
                     "definitions": pair["definitions"], "dictionary_evidence": meanings})
    return {"pairs_hash": dataset["pairs_hash"], "source": "installed JMdict via jamdict",
            "evidence": rows, "evidence_hash": digest(rows)}


def metrics(records, threshold):
    accepted = [r for r in records if threshold is not None and r["cosine"] >= threshold]
    counts = Counter(r["label"] for r in accepted)
    good = counts["equivalent"]
    n = len(accepted)
    # Wilson lower bound is descriptive only: labels are provisional and sampled.
    z = 1.96
    lower = ((good/n + z*z/(2*n) - z*((good/n*(1-good/n)/n + z*z/(4*n*n))**.5))
             / (1+z*z/n)) if n else None
    return {"cases": len(records), "labels": dict(Counter(r["label"] for r in records)),
            "accepted": n, "equivalent_accepted": good,
            "false_merges": counts["distinct"], "uncertain_accepted": counts["uncertain"],
            "coverage": n/len(records) if records else 0,
            "provisional_precision": good/n if n else None,
            "provisional_wilson_lower_95": lower}


def choose_threshold(calibration):
    """Maximize coverage with zero distinct/uncertain merges on calibration only."""
    choices = []
    for threshold in sorted({r["cosine"] for r in calibration}):
        measured = metrics(calibration, threshold)
        if measured["accepted"] and not (measured["false_merges"] or measured["uncertain_accepted"]):
            choices.append((measured["equivalent_accepted"], threshold))
    return max(choices)[1] if choices else None


def evaluate(dataset, annotations, reports, evidence=None):
    pairs = validate_pairs(dataset)
    pilot = {p["case_id"]: p for p in pairs if p["pilot"]}
    if annotations.get("label_provenance") != "model_draft_not_human_gold" or not annotations.get("annotator"):
        raise ValueError("explicit machine label provenance required")
    rows = annotations["labels"]
    labels = {r["case_id"]: r for r in rows}
    if len(labels) != len(rows) or set(labels) != set(pilot):
        raise ValueError("pilot annotations must cover each pair exactly once")
    if any(r["label"] not in LABELS or not r.get("reason") for r in rows):
        raise ValueError("invalid annotation")
    if annotations.get("pairs_hash") != dataset["pairs_hash"]:
        raise ValueError("annotation fingerprint mismatch")
    if annotations.get("evidence_hash"):
        if (not evidence or evidence["pairs_hash"] != dataset["pairs_hash"]
                or digest(evidence["evidence"]) != evidence["evidence_hash"]
                or annotations["evidence_hash"] != evidence["evidence_hash"]):
            raise ValueError("dictionary evidence fingerprint mismatch")
    results = []
    for report in reports:
        if report["pairs_hash"] != digest(pairs):
            raise ValueError("scored dataset fingerprint mismatch")
        scores = report["records"]
        if len(scores) != len(pairs) or {r["case_id"] for r in scores} != {p["case_id"] for p in pairs}:
            raise ValueError("scored pair coverage mismatch")
        frozen = {p["case_id"]: p for p in pairs}
        if any({k: r.get(k) for k in frozen[r["case_id"]]} != frozen[r["case_id"]]
               or not isinstance(r.get("cosine"), (int, float))
               or not math.isfinite(r["cosine"]) or not -1 <= r["cosine"] <= 1
               for r in scores):
            raise ValueError("scored pair input or cosine mismatch")
        records = [{**pilot[r["case_id"]], "cosine": r["cosine"],
                    "label": labels[r["case_id"]]["label"]}
                   for r in scores if r["case_id"] in pilot]
        cal = [r for r in records if r["split"] == "calibration"]
        test = [r for r in records if r["split"] == "heldout"]
        if not cal or not test:
            raise ValueError("both pilot splits required")
        threshold = choose_threshold(cal)
        results.append({"model": report["model"], "experimental_threshold": threshold,
                        "calibration": metrics(cal, threshold), "heldout": metrics(test, threshold),
                        "calibration_curve": [{"threshold": t/100, **metrics(cal, t/100)}
                                              for t in range(-100, 101, 2)],
                        "pilot_records": records})
    return {"schema_version": 1, "dataset_hash": dataset["pairs_hash"],
            "annotations_hash": digest(annotations), "label_provenance": annotations["label_provenance"],
            "gold_scored": 0, "production_ready": False, "results": results,
            "selection_rule": "lowest observed calibration boundary with maximum equivalent coverage and zero distinct/uncertain merges; None means abstain on all",
            "warning": "Machine draft labels; diagnostic precision, not independently validated reliability."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--source", required=True)
    build.add_argument("--output", required=True)
    evidence = sub.add_parser("evidence")
    evidence.add_argument("--dataset", required=True)
    evidence.add_argument("--output", required=True)
    score = sub.add_parser("evaluate")
    score.add_argument("--dataset", required=True)
    score.add_argument("--annotations", required=True)
    score.add_argument("--evidence", help="required for metadata-reviewed annotation fingerprints")
    score.add_argument("--reports", nargs="+", required=True)
    score.add_argument("--output", required=True)
    args = parser.parse_args()
    read = lambda p: json.loads(Path(p).read_text())
    if args.command == "build":
        result = build_pool(read(args.source)["cards"])
        validate_pairs(result)
    elif args.command == "evidence":
        result = source_evidence(read(args.dataset))
    else:
        result = evaluate(read(args.dataset), read(args.annotations), [read(p) for p in args.reports],
                          read(args.evidence) if args.evidence else None)
    _write(args.output, result)
    print(json.dumps({"output": args.output, "pairs": len(result.get("pairs", [])),
                      "models": len(result.get("results", []))}))


if __name__ == "__main__":
    main()
