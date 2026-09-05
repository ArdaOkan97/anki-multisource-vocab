"""Replay saved validation evidence; no inference, media extraction or deck writes."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from .context_meanings import context_meaning_issues
from .semantic_benchmark import digest, _write
from .validation import (
    _context_learning_units, _initial_known_learning_units, _learning_unit_key,
    plan_review_frontier, select_validated_curriculum,
)


def verify_sequence(cards, selection, decisions, harder_unknown_tolerance=2.0):
    known = {u for c in cards for u in (_initial_known_learning_units(c) or set())}
    used, taught = set(), set()
    difficulties = {_learning_unit_key(c): float(c.get("difficulty_score") or 0.) for c in cards}
    for c in selection["accepted"]:
        unit, sentence = _learning_unit_key(c), int(c.get("sentence_id") or 0)
        assert unit not in taught and sentence not in used
        assert decisions[int(c["audit_position"])] == "accepted"
        assert not context_meaning_issues(c)
        context = _context_learning_units(c)
        assert context is not None and _initial_known_learning_units(c) is not None
        unknown = context - {unit} - known
        assert unknown == set(c["scheduling"]["unknown_context_learning_unit_keys"])
        assert len(unknown) <= c["scheduling"]["unknown_allowance"]
        assert all(u in difficulties for u in unknown)
        if harder_unknown_tolerance is not None:
            assert all(difficulties[u] - difficulties[unit] <= harder_unknown_tolerance for u in unknown)
        known.add(unit)
        taught.add(unit)
        used.add(sentence)
    return {"unique_sentences": True, "unique_exact_learning_units": True,
            "accepted_validation_only": True, "prior_known_only_unknown_limits": True,
            "configured_difficulty_gap_preserved": True,
            "context_metadata_policy_preserved": True}


def compare(cards, validation, limit=200, harder_unknown_tolerance=2.0):
    decisions = {int(r["audit_position"]): r["decision"]["status"]
                 for status in ("accepted", "rejected", "abstained") for r in validation.get(status, [])}
    runs = {}
    for strategy in ("greedy", "reassign"):
        start = time.perf_counter()
        selection = select_validated_curriculum(cards, validation, strategy=strategy, limit=limit,
                                               harder_unknown_tolerance=harder_unknown_tolerance)
        elapsed = time.perf_counter() - start
        runs[strategy] = {"selection": selection, "seconds": elapsed,
                          "structural_checks": verify_sequence(cards, selection, decisions, harder_unknown_tolerance)}
    old, new = [runs[k]["selection"]["accepted"] for k in ("greedy", "reassign")]
    old_by_unit = {_learning_unit_key(c): c for c in old}
    new_by_unit = {_learning_unit_key(c): c for c in new}
    frontier = plan_review_frontier(cards, selected_cards=new, validation_report=validation,
                                   harder_unknown_tolerance=harder_unknown_tolerance)
    watched = {}
    for word in ("誰", "お前", "君"):
        candidates = [c for c in cards if c.get("lemma") == word]
        watched[word] = {"candidates": len(candidates), "statuses": dict(Counter(
            decisions.get(int(c["audit_position"]), "unreviewed") for c in candidates)),
            "selected_before": [c["audit_position"] for c in old if c.get("lemma") == word],
            "selected_after": [c["audit_position"] for c in new if c.get("lemma") == word]}
    return {"schema_version": 1, "candidate_hash": digest(cards), "validation_hash": digest(validation),
            "config": {"limit": limit, "harder_unknown_tolerance": harder_unknown_tolerance,
                       "zero_unknown_through": 20, "one_unknown_through": 200,
                       "later_unknown_limit": 2, "frontier_size": 100,
                       "max_reassignment_states": 64, "max_reassignment_depth": 3},
            "input_candidates": len(cards), "validation_statuses": dict(Counter(decisions.values())),
            "unreviewed": sum(int(c["audit_position"]) not in decisions for c in cards),
            "legacy_context_candidates": sum("context_meanings_version" not in c for c in cards),
            "runs": runs, "yield_delta": len(new) - len(old),
            "added_units": sorted(new_by_unit.keys() - old_by_unit.keys()),
            "removed_units": sorted(old_by_unit.keys() - new_by_unit.keys()),
            "changed_assignments": [{"unit": u, "before": old_by_unit[u]["audit_position"],
                                     "after": new_by_unit[u]["audit_position"]}
                                    for u in old_by_unit.keys() & new_by_unit.keys()
                                    if old_by_unit[u]["audit_position"] != new_by_unit[u]["audit_position"]],
            "watched_words": watched,
            "planned_replacements": [c["audit_position"] for c in frontier["cards"]
                                     if c["review_planning"]["purpose"] == "sentence_replacement"],
            "note": "Matched saved-evidence scheduling replay, not new semantic/audio validation or a fresh baseline-quality review."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidates", required=True)
    p.add_argument("--validation", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--summary-output", help="optional compact reproducible report without full candidate/card bodies")
    p.add_argument("--soft-harder-unknowns", action="store_true",
                   help="historical diagnostic replay only: disable harder-unknown gap check in BOTH arms")
    args = p.parse_args()
    read = lambda path: json.loads(Path(path).read_text())
    report = compare(read(args.candidates)["cards"], read(args.validation),
                     harder_unknown_tolerance=None if args.soft_harder_unknowns else 2.0)
    _write(args.output, report)
    if args.summary_output:
        compact = {k: v for k, v in report.items() if k != "runs"}
        compact["runs"] = {k: {"summary": v["selection"]["summary"],
                               "search": v["selection"]["reassignment_search"],
                               "seconds": v["seconds"], "structural_checks": v["structural_checks"]}
                           for k, v in report["runs"].items()}
        _write(args.summary_output, compact)
    print(json.dumps({"yield_delta": report["yield_delta"],
                      "runs": {k: {"accepted": v["selection"]["summary"]["accepted"],
                                   "search": v["selection"]["reassignment_search"],
                                   "seconds": v["seconds"]} for k, v in report["runs"].items()},
                      "watched_words": report["watched_words"],
                      "planned_replacements": report["planned_replacements"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
