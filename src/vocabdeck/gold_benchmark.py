from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .constrained_review import SENSE_PROMPT_VERSION, SUPPORT_PROMPT_VERSION


DATASET_SCHEMA_VERSION = 1
PREDICTION_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
ACCEPTANCE_POLICY_VERSION = 1
LABEL_VALUES = {
    "sense": {"expected", "unsupported", "ambiguous", "unreviewed"},
    "subtitle_support": {"expressed", "not_expressed", "ambiguous", "unreviewed"},
    "production": {"accept", "reject", "unreviewed"},
}
CARD_FIELDS = (
    "position", "audit_position", "candidate_key", "learning_unit_key", "sense_key",
    "lemma", "reading", "part_of_speech", "gloss", "target_surface", "japanese",
    "english", "series", "season", "episode", "cue_index", "sentence_id",
    "start_ms", "end_ms", "target_start", "target_end",
)

VERIFIER_PROMPT_FIELDS = (
    "candidate_key", "learning_unit_key", "sense_key",
    "lemma", "reading", "part_of_speech", "gloss", "target_surface",
    "japanese", "english", "series", "season", "episode", "cue_index",
    "sentence_id", "target_start", "target_end",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cards(path: Path) -> List[Dict[str, Any]]:
    value = _read_json(path)
    rows = value.get("cards", []) if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError(f"card artifact must contain a list: {path}")
    return [dict(row) for row in rows]


def _project_card(card: Mapping[str, Any], *, default_series: str = "") -> Dict[str, Any]:
    projected = {key: card.get(key) for key in CARD_FIELDS if card.get(key) is not None}
    if default_series and not projected.get("series"):
        projected["series"] = default_series
    return projected


def _stable_id(split: str, card: Mapping[str, Any], mutation: str = "original") -> str:
    identity = {
        "split": split,
        "mutation": mutation,
        "candidate_key": card.get("candidate_key"),
        "series": card.get("series"),
        "episode": card.get("episode"),
        "cue_index": card.get("cue_index"),
        "sense_key": card.get("sense_key"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"{split}-{digest}"


def verifier_case_id(card: Mapping[str, Any]) -> str:
    """Fingerprint verifier input independently of artifact-local ordering."""
    prompt_input = {
        key: card.get(key) for key in VERIFIER_PROMPT_FIELDS
        if card.get(key) is not None
    }
    digest = hashlib.sha256(
        json.dumps(prompt_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"production-{digest}"


def build_candidate_dataset(
    cards: Sequence[Mapping[str, Any]], *, source_artifact: str = "",
) -> Dict[str, Any]:
    """Wrap production candidates without inventing gold labels."""
    unreviewed = _labels("unreviewed", "unreviewed", "unreviewed", [], None)
    rows = []
    for card in cards:
        projected = _project_card(card)
        rows.append({
            "schema_version": DATASET_SCHEMA_VERSION,
            "case_id": verifier_case_id(card),
            "split": "production_candidates",
            "review_status": "unreviewed",
            "card": projected,
            "labels": unreviewed,
            "provenance": {
                "kind": "production_candidate",
                "reviewer": None,
                "source_artifact": source_artifact,
            },
            "tags": [],
        })
    dataset = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_id": "vocab-verifier-production-candidates-v1",
        "description": "Unlabeled production candidates for fail-closed verification.",
        "prompt_versions": {
            "sense": SENSE_PROMPT_VERSION,
            "subtitle_support": SUPPORT_PROMPT_VERSION,
            "acceptance_policy": ACCEPTANCE_POLICY_VERSION,
        },
        "splits": {"production_candidates": rows},
        "source_policy": {
            "llm_outputs_are_gold": False,
            "unreviewed_queues_are_scored": False,
        },
    }
    validate_dataset(dataset)
    return dataset


def _labels(
    sense: str, subtitle_support: str, production: str,
    reasons: Sequence[str], correct_sense_key: Optional[str],
) -> Dict[str, Any]:
    return {
        "sense": sense,
        "correct_sense_key": correct_sense_key,
        "subtitle_support": subtitle_support,
        "production": production,
        "reasons": list(reasons),
    }


def _case(
    split: str, card: Mapping[str, Any], *, review_status: str,
    labels: Mapping[str, Any], provenance: Mapping[str, Any],
    tags: Sequence[str] = (), mutation: str = "original",
) -> Dict[str, Any]:
    projected = _project_card(card)
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "case_id": _stable_id(split, projected, mutation),
        "split": split,
        "review_status": review_status,
        "card": projected,
        "labels": dict(labels),
        "provenance": dict(provenance),
        "tags": sorted(set(tags)),
    }


def _deterministic_queue(cards: Sequence[Mapping[str, Any]], split: str, size: int) -> List[Dict[str, Any]]:
    def key(card: Mapping[str, Any]) -> str:
        projected = _project_card(card)
        return _stable_id(split, projected)

    selected = sorted(cards, key=key)[:max(0, int(size))]
    unreviewed = _labels("unreviewed", "unreviewed", "unreviewed", [], None)
    return [
        _case(
            split, card, review_status="unreviewed", labels=unreviewed,
            provenance={"kind": "review_queue", "reviewer": None},
        )
        for card in selected
    ]


def _hard_negative(
    card: Mapping[str, Any], *, tags: Sequence[str], mutation: str,
    reasons: Sequence[str], reviewer: str = "deterministic-fixture",
) -> Dict[str, Any]:
    return _case(
        "hard_negatives", card, review_status="gold",
        labels=_labels("unsupported", "not_expressed", "reject", reasons, None),
        provenance={
            "kind": "synthetic_rule", "reviewer": reviewer,
            "mutation": mutation,
        },
        tags=tags, mutation=mutation,
    )


def build_gold_dataset(
    baseline_path: Path, human_review_path: Path,
    heldout_hxh_path: Path, second_show_path: Path, *, queue_size: int = 40,
) -> Dict[str, Any]:
    baseline = _cards(baseline_path)
    review = _read_json(human_review_path)
    start = int(review["reviewed_range"]["start"])
    end = int(review["reviewed_range"]["end"])
    flagged = {int(row["position"]): row for row in review["flagged_cards"]}
    by_position = {int(row["position"]): row for row in baseline}
    development = []
    for position in range(start, end + 1):
        card = _project_card(by_position[position], default_series="Hunter x Hunter")
        finding = flagged.get(position)
        if finding is None:
            labels = _labels(
                "expected", "expressed", "accept", [], card.get("sense_key")
            )
            provenance = {
                "kind": "human_review", "reviewer": "project-owner",
                "decision": "implicit_pass_in_reviewed_range", "position": position,
            }
        else:
            categories = list(finding["categories"])
            sense = "unsupported" if "wrong_contextual_sense" in categories else "expected"
            support = "ambiguous" if "subtitle_contamination" in categories else "expressed"
            labels = _labels(
                sense, support, "reject", categories,
                card.get("sense_key") if sense == "expected" else None,
            )
            provenance = {
                "kind": "human_review", "reviewer": "project-owner",
                "decision": "explicit_flag", "position": position,
                "user_note": finding.get("user_note"),
            }
        development.append(_case(
            "development", card, review_status="gold", labels=labels,
            provenance=provenance, tags=labels["reasons"],
        ))

    # Known human findings are copied into the hard-negative suite, while subtitle
    # swaps provide transparent negatives for fragile utterance classes.
    hard_negatives = []
    for position, tags in (
        (40, ("homograph_or_alternate_reading",)),
        (78, ("wrong_sense", "larger_expression")),
    ):
        source = next(row for row in development if row["card"]["position"] == position)
        copy = dict(source)
        copy["split"] = "hard_negatives"
        copy["case_id"] = _stable_id("hard_negatives", copy["card"], f"human-{position}")
        copy["tags"] = sorted(set(copy["tags"]) | set(tags))
        copy["provenance"] = {
            **copy["provenance"], "copied_from": source["case_id"],
        }
        hard_negatives.append(copy)
    swaps = (
        (7, 8, ("nearby_wrong_subtitle", "one_word")),
        (24, 25, ("nearby_wrong_subtitle", "fragment")),
        (72, 73, ("nearby_wrong_subtitle", "slang")),
    )
    for position, donor_position, tags in swaps:
        mutated = dict(_project_card(by_position[position], default_series="Hunter x Hunter"))
        mutated["english"] = by_position[donor_position]["english"]
        hard_negatives.append(_hard_negative(
            mutated, tags=tags, mutation=f"english-from-{donor_position}",
            reasons=("nearby_incorrect_subtitle",),
        ))

    dataset = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_id": "vocab-verifier-gold-v1",
        "description": "Human gold plus frozen unlabeled queues and transparent hard negatives.",
        "prompt_versions": {
            "sense": SENSE_PROMPT_VERSION,
            "subtitle_support": SUPPORT_PROMPT_VERSION,
            "acceptance_policy": ACCEPTANCE_POLICY_VERSION,
        },
        "splits": {
            "development": development,
            "heldout_hxh": _deterministic_queue(
                _cards(heldout_hxh_path), "heldout_hxh", queue_size
            ),
            "second_show": _deterministic_queue(
                _cards(second_show_path), "second_show", queue_size
            ),
            "hard_negatives": hard_negatives,
        },
        "source_policy": {
            "llm_outputs_are_gold": False,
            "unreviewed_queues_are_scored": False,
            "human_review_baseline": str(review.get("baseline_id") or ""),
        },
        "source_artifacts": {
            "baseline": {"name": baseline_path.name, "sha256": _sha256(baseline_path)},
            "human_review": {"name": human_review_path.name, "sha256": _sha256(human_review_path)},
            "heldout_hxh": {"name": heldout_hxh_path.name, "sha256": _sha256(heldout_hxh_path)},
            "second_show": {"name": second_show_path.name, "sha256": _sha256(second_show_path)},
        },
    }
    validate_dataset(dataset)
    return dataset


def iter_cases(dataset: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for split in dataset.get("splits", {}).values():
        yield from split


def validate_dataset(dataset: Mapping[str, Any]) -> None:
    if dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported dataset schema version")
    if not isinstance(dataset.get("splits"), dict):
        raise ValueError("dataset splits are required")
    seen = set()
    for case in iter_cases(dataset):
        case_id = case.get("case_id")
        if not case_id or case_id in seen:
            raise ValueError("case IDs must be present and unique")
        seen.add(case_id)
        if case.get("schema_version") != DATASET_SCHEMA_VERSION:
            raise ValueError(f"invalid case schema: {case_id}")
        if case.get("review_status") not in {"gold", "unreviewed"}:
            raise ValueError(f"invalid review status: {case_id}")
        labels = case.get("labels", {})
        for name, allowed in LABEL_VALUES.items():
            if labels.get(name) not in allowed:
                raise ValueError(f"invalid {name} label: {case_id}")
        if case["review_status"] == "gold" and labels["production"] == "unreviewed":
            raise ValueError(f"gold case lacks production judgment: {case_id}")
        if case["review_status"] == "unreviewed" and any(
            labels[name] != "unreviewed" for name in LABEL_VALUES
        ):
            raise ValueError(f"unreviewed case contains a gold judgment: {case_id}")
        provenance = case.get("provenance", {})
        if "kind" not in provenance or "reviewer" not in provenance:
            raise ValueError(f"reviewer provenance is required: {case_id}")


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> List[float]:
    if total <= 0:
        return [0.0, 1.0]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def evaluate_predictions(
    dataset: Mapping[str, Any], predictions: Mapping[str, Any], *,
    precision_target: float = 0.995, minimum_accepted_gold: int = 600,
    allow_prompt_version_override: bool = False,
) -> Dict[str, Any]:
    validate_dataset(dataset)
    expected_prompts = dataset["prompt_versions"]
    prediction_prompts = predictions.get("prompt_versions") or {}
    versions_match = prediction_prompts == expected_prompts
    ab_override_is_safe = (
        allow_prompt_version_override
        and prediction_prompts.get("acceptance_policy")
        == expected_prompts.get("acceptance_policy")
        and prediction_prompts.get("sense")
        == prediction_prompts.get("subtitle_support")
        and isinstance(prediction_prompts.get("sense"), int)
    )
    if not versions_match and not ab_override_is_safe:
        raise ValueError("prediction prompt/rule versions do not match the dataset")
    by_id = {row.get("case_id"): row for row in predictions.get("records", [])}
    gold = [row for row in iter_cases(dataset) if row["review_status"] == "gold"]
    counters: Counter[str] = Counter()
    tags: Dict[str, Counter[str]] = defaultdict(Counter)
    records = []
    for case in gold:
        prediction = by_id.get(case["case_id"])
        expected_accept = case["labels"]["production"] == "accept"
        semantic_expected_accept = (
            case["labels"]["sense"] == "expected"
            and case["labels"]["subtitle_support"] == "expressed"
        )
        if prediction is None:
            accepted, abstained, invalid = False, True, True
            prediction = {"case_id": case["case_id"], "reason": "missing_prediction"}
        else:
            accepted = bool(prediction.get("accepted", False))
            invalid = bool(prediction.get("invalid_output", False))
            abstained = bool(prediction.get("abstained", not accepted))
        votes = prediction.get("sense_votes") or []
        unstable = len(votes) >= 2 and len(set(map(str, votes))) > 1
        outcome = (
            "true_accept" if accepted and expected_accept else
            "false_accept" if accepted else
            "false_reject" if expected_accept else "true_reject"
        )
        semantic_outcome = (
            "true_accept" if accepted and semantic_expected_accept else
            "false_accept" if accepted else
            "false_reject" if semantic_expected_accept else "true_reject"
        )
        counters[outcome] += 1
        counters[f"semantic_{semantic_outcome}"] += 1
        counters["accepted" if accepted else "not_accepted"] += 1
        counters["abstained"] += int(abstained)
        counters["invalid_outputs"] += int(invalid)
        counters["option_order_unstable"] += int(unstable)
        for tag in case.get("tags", []):
            tags[tag][outcome] += 1
            tags[tag]["evaluated"] += 1
            tags[tag]["abstentions"] += int(abstained)
            tags[tag]["invalid_outputs"] += int(invalid)
            tags[tag]["option_order_unstable"] += int(unstable)
        records.append({
            "case_id": case["case_id"], "split": case["split"],
            "expected_accept": expected_accept, "accepted": accepted,
            "outcome": outcome, "abstained": abstained,
            "semantic_expected_accept": semantic_expected_accept,
            "semantic_outcome": semantic_outcome,
            "invalid_output": invalid, "option_order_unstable": unstable,
            "reason": prediction.get("reason"),
        })
    accepted = counters["accepted"]
    precision = counters["true_accept"] / accepted if accepted else 0.0
    interval = _wilson_interval(counters["true_accept"], accepted)
    eligible = accepted >= minimum_accepted_gold
    claim = eligible and interval[0] >= precision_target
    summary_in = predictions.get("summary", {})
    subgroup_results = {}
    for name, values in sorted(tags.items()):
        subgroup_accepted = values["true_accept"] + values["false_accept"]
        subgroup_positive = values["true_accept"] + values["false_reject"]
        subgroup_results[name] = {
            **dict(values),
            "accepted_precision": round(
                values["true_accept"] / subgroup_accepted, 6
            ) if subgroup_accepted else None,
            "accepted_precision_95ci": [
                round(value, 6) for value in _wilson_interval(
                    values["true_accept"], subgroup_accepted
                )
            ],
            "acceptance_coverage": round(
                subgroup_accepted / values["evaluated"], 6
            ) if values["evaluated"] else 0.0,
            "positive_coverage": round(
                values["true_accept"] / subgroup_positive, 6
            ) if subgroup_positive else None,
            "abstention_rate": round(
                values["abstentions"] / values["evaluated"], 6
            ) if values["evaluated"] else 0.0,
            "invalid_output_rate": round(
                values["invalid_outputs"] / values["evaluated"], 6
            ) if values["evaluated"] else 0.0,
            "option_order_disagreement_rate": round(
                values["option_order_unstable"] / values["evaluated"], 6
            ) if values["evaluated"] else 0.0,
        }
    positives = counters["true_accept"] + counters["false_reject"]
    semantic_accepted = (
        counters["semantic_true_accept"] + counters["semantic_false_accept"]
    )
    semantic_positives = (
        counters["semantic_true_accept"] + counters["semantic_false_reject"]
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "dataset_id": dataset.get("dataset_id"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_versions": dict(prediction_prompts),
        "dataset_prompt_versions": dict(expected_prompts),
        "model": predictions.get("model"),
        "summary": {
            "gold_evaluated": len(gold), "accepted": accepted,
            "true_accepts": counters["true_accept"],
            "false_accepts": counters["false_accept"],
            "true_rejects": counters["true_reject"],
            "false_rejects": counters["false_reject"],
            "accepted_precision": round(precision, 6),
            "accepted_precision_95ci": [round(value, 6) for value in interval],
            "acceptance_coverage": round(accepted / len(gold), 6) if gold else 0.0,
            "positive_coverage": round(
                counters["true_accept"] / positives, 6
            ) if positives else 0.0,
            "semantic_true_accepts": counters["semantic_true_accept"],
            "semantic_false_accepts": counters["semantic_false_accept"],
            "semantic_true_rejects": counters["semantic_true_reject"],
            "semantic_false_rejects": counters["semantic_false_reject"],
            "semantic_accepted_precision": round(
                counters["semantic_true_accept"] / semantic_accepted, 6
            ) if semantic_accepted else 0.0,
            "semantic_positive_coverage": round(
                counters["semantic_true_accept"] / semantic_positives, 6
            ) if semantic_positives else 0.0,
            "abstentions": counters["abstained"],
            "abstention_rate": round(counters["abstained"] / len(gold), 6) if gold else 0.0,
            "option_order_unstable": counters["option_order_unstable"],
            "invalid_outputs": counters["invalid_outputs"],
            "cards_per_second": summary_in.get("cards_per_second"),
            "peak_memory_gb": summary_in.get("peak_memory_gb"),
            "artifact_size_gb": summary_in.get("artifact_size_gb"),
            "cleanup_verified": summary_in.get("cleanup_verified", False),
            "precision_target": precision_target,
            "minimum_accepted_gold": minimum_accepted_gold,
            "precision_claim_supported": claim,
            "precision_claim_reason": (
                "wilson_lower_bound_meets_target" if claim else
                "insufficient_accepted_gold" if not eligible else
                "confidence_bound_below_target"
            ),
        },
        "subgroups": subgroup_results,
        "records": records,
    }


def render_blinded_html(
    dataset: Mapping[str, Any], report: Mapping[str, Any], destination: Path
) -> Path:
    validate_dataset(dataset)
    cases = {row["case_id"]: row for row in iter_cases(dataset)}
    blocks = []
    for index, result in enumerate(report.get("records", []), 1):
        case = cases[result["case_id"]]
        card = case["card"]
        alias = hashlib.sha256(result["case_id"].encode("utf-8")).hexdigest()[:8]
        expected = "accept" if result["expected_accept"] else "reject"
        blocks.append(f"""
<article><h2>#{index} Candidate {alias}</h2>
<p class=jp>{html.escape(str(card.get('japanese') or ''))}</p>
<p>{html.escape(str(card.get('english') or ''))}</p>
<p><b>{html.escape(str(card.get('target_surface') or card.get('lemma') or ''))}</b>
 · {html.escape(str(card.get('gloss') or ''))}</p>
<p>Verifier: <strong>{'accept' if result['accepted'] else 'abstain/reject'}</strong>
 · {html.escape(str(result.get('reason') or ''))}</p>
<details><summary>Reveal gold judgment</summary><p>{expected} · {html.escape(result['outcome'])}</p>
<p>{html.escape(', '.join(case['labels'].get('reasons', [])) or 'No flagged reason')}</p></details></article>""")
    summary = report["summary"]
    document = f"""<!doctype html><html><head><meta charset=utf-8>
<title>Blinded verifier review</title><style>
body{{max-width:900px;margin:40px auto;background:#202124;color:#eee;font:18px system-ui}}
article{{border:1px solid #555;border-radius:14px;padding:22px;margin:18px 0}}
.jp{{font-size:30px}} .meta{{color:#aaa}} summary{{cursor:pointer;color:#b9a7ff}}
</style></head><body><h1>Blinded verifier review</h1>
<p class=meta>{summary['gold_evaluated']} gold cases · {summary['false_accepts']} false accepts · precision claim: {str(summary['precision_claim_supported']).lower()}</p>
{''.join(blocks)}</body></html>"""
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination


def write_json(value: Mapping[str, Any], destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination
