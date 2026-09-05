"""Small dictionary-meaning probe, separate from contextual equivalence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from .constrained_review import SensePrompt, parse_label
from .semantic_benchmark import case_fingerprint, digest, validate_dataset, _write


def build_pairs(dataset):
    validate_dataset(dataset)
    pairs = []
    for source in dataset["cases"]:
        if source["task"] != "equivalence":
            continue
        items = [source["input"][side] for side in ("left", "right")]
        meanings = []
        for item in items:
            selected = item["card"]["sense_key"]
            matches = [o for o in item["options"] if o["sense_key"] == selected]
            if len(matches) != 1:
                raise ValueError("source meaning must be present in frozen dictionary options")
            meanings.append(dict(matches[0]))
        pairs.append({"word": items[0]["card"]["lemma"], "meanings": meanings,
                      "source_case_id": source["case_id"],
                      "source_fingerprint": case_fingerprint(source),
                      "kind": "dictionary_pair", "gold": None})
    # Structural sanity controls, not independently annotated semantic gold.
    controls = []
    for pair in pairs[:2]:
        controls.append({**pair, "kind": "identical_gloss_control",
                         "meanings": [dict(pair["meanings"][0]), dict(pair["meanings"][0])]})
    for pair in pairs + controls:
        pair["case_id"] = "dictionary-pair-" + digest(pair)[:24]
    return pairs + controls


def build_prompt(pair, round_index):
    meanings = list(pair["meanings"])
    if round_index % 2:
        meanings.reverse()
    choices = [("same", "Equivalent"), ("different", "Different"), (None, "Unsure")]
    shift = round_index % 3
    choices = choices[shift:] + choices[:shift]
    mapping = {chr(65 + i): value for i, (value, _) in enumerate(choices)}
    return SensePrompt("\n".join([
        f"Word: {pair['word']}",
        f"Meaning 1: {meanings[0]['gloss']}",
        f"Meaning 2: {meanings[1]['gloss']}", "",
        "Do these meanings describe the same use of this word?", "",
        *[f"{chr(65+i)}. {label}" for i, (_, label) in enumerate(choices)], "",
        "Answer with one letter.",
    ]), mapping)


def run_probe(pairs, reviewer, checkpoint=None):
    if not pairs:
        raise ValueError("no dictionary pairs")
    report = {"schema_version": 1, "prompt_version": "simple-dictionary-pair-v1",
              "task": "dictionary_equivalence_not_contextual_equivalence",
              "model": reviewer.model_name, "pairs_hash": digest(pairs),
              "records": [], "summary": {}}
    started = time.perf_counter()
    peak = 0.0
    for pair in pairs:
        prompts = [build_prompt(pair, i) for i in range(2)]
        raw, stats = reviewer.review([p.prompt for p in prompts])
        peak = max(peak, float(stats.get("peak_memory", 0)))
        parsed, relation, reason = [], None, "invalid_output"
        if len(raw) == 2:
            try:
                parsed = [parse_label(text, p.label_to_sense) for text, p in zip(raw, prompts)]
                if parsed[0] != parsed[1]:
                    reason = "order_disagreement"
                else:
                    relation = parsed[0]
                    reason = "stable" if relation is not None else "uncertain"
            except ValueError:
                pass
        report["records"].append({
            "case": pair, "input_fingerprint": digest(pair),
            "prompts": [p.prompt for p in prompts],
            "mappings": [p.label_to_sense for p in prompts], "raw": raw,
            "parsed": parsed, "relation": relation, "reason": reason,
        })
        report["summary"] = {"evaluated": len(report["records"]),
                             "prompt_calls": len(report["records"]) * 2,
                             "elapsed_seconds": time.perf_counter() - started,
                             "peak_memory_gb": peak, "gold_scored": 0}
        if checkpoint:
            checkpoint(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--memory-limit-gb", type=float, default=4.0)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    pairs = build_pairs(json.loads(Path(args.dataset).read_text()))[:args.limit]
    if not pairs:
        parser.error("no dictionary pairs")
    from .constrained_review import MLXLabelReviewer
    reviewer = MLXLabelReviewer(args.model, revision=args.revision,
                                memory_limit_gb=args.memory_limit_gb)
    try:
        report = run_probe(pairs, reviewer, lambda value: _write(args.output, value))
    finally:
        reviewer.close()
    report["summary"]["cleanup_completed"] = True
    report["runtime_config"] = {"memory_limit_gb": args.memory_limit_gb,
                                "max_tokens": 4, "max_kv_size": 1024, "temperature": 0.0,
                                "model": args.model, "revision": args.revision}
    _write(args.output, report)
    print(json.dumps({"model": args.model, **report["summary"]}))


if __name__ == "__main__":
    main()
