from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .gold_benchmark import iter_cases, validate_dataset


SMOKE_SIZE = 20


def build_smoke_dataset(dataset: Mapping[str, Any], size: int = SMOKE_SIZE) -> Dict[str, Any]:
    validate_dataset(dataset)
    gold = [row for row in iter_cases(dataset) if row["review_status"] == "gold"]
    rejects = [row for row in gold if row["labels"]["production"] == "reject"]
    accepts = [row for row in gold if row["labels"]["production"] == "accept"]

    def stable_order(row: Mapping[str, Any]) -> str:
        return hashlib.sha256(str(row["case_id"]).encode("utf-8")).hexdigest()

    reject_count = min(len(rejects), max(1, size // 2))
    selected = sorted(rejects, key=stable_order)[:reject_count]
    selected.extend(sorted(accepts, key=stable_order)[:max(0, size - len(selected))])
    smoke = {key: value for key, value in dataset.items() if key != "splits"}
    smoke["dataset_id"] = f"{dataset.get('dataset_id')}-smoke-{size}"
    smoke["description"] = "Sequential guarded smoke cohort; all records are gold."
    smoke["splits"] = {"smoke": selected}
    validate_dataset(smoke)
    return smoke


def build_comparison_report(
    evaluations: Sequence[Mapping[str, Any]],
    candidate_config: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    rows = []
    for evaluation in evaluations:
        model = str(evaluation.get("model") or "")
        model_id = model.split("@", 1)[0]
        config = candidate_config.get(model_id, {})
        summary = dict(evaluation["summary"])
        if not summary.get("cleanup_verified"):
            status = "resource_or_cleanup_failure"
        elif int(summary.get("false_accepts") or 0) > 0:
            status = "failed_smoke_false_accept"
        elif int(summary.get("accepted") or 0) == 0:
            status = "failed_smoke_zero_coverage"
        else:
            status = "passed_smoke"
        rows.append({
            "model": model,
            "revision": config.get("revision"),
            "role": config.get("role"),
            "status": status,
            "summary": summary,
            "subgroups": evaluation.get("subgroups", {}),
            "full_split_status": {
                "development": "not_run_smoke_gate" if status != "passed_smoke" else "eligible",
                "heldout_hxh": "not_run_smoke_gate" if status != "passed_smoke" else "eligible_unreviewed",
                "second_show": "not_run_smoke_gate" if status != "passed_smoke" else "eligible_unreviewed",
                "hard_negatives": "not_run_smoke_gate" if status != "passed_smoke" else "eligible",
            },
        })
    eligible = [
        row for row in rows
        if row["status"] == "passed_smoke"
        and row["summary"].get("precision_claim_supported")
    ]
    if eligible:
        chosen = max(
            eligible,
            key=lambda row: (
                row["summary"].get("accepted_precision") or 0,
                row["summary"].get("positive_coverage") or 0,
            ),
        )
        recommendation = {"decision": "adopt", "model": chosen["model"]}
    else:
        recommendation = {
            "decision": "retain_deterministic_baseline",
            "reason": (
                "No candidate passed the smoke gate; no candidate has sufficient "
                "held-out evidence for the production precision claim."
            ),
        }
    return {
        "schema_version": 1,
        "comparison_policy_version": 1,
        "candidates": rows,
        "recommendation": recommendation,
    }


def load_candidate_config(path: Path) -> Dict[str, Dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = [dict(row) for row in value["candidates"]]
    fallback = dict(value.get("fallback") or {})
    if fallback.get("model"):
        fallback["role"] = "fallback"
        rows.append(fallback)
    return {str(row["model"]): row for row in rows}
