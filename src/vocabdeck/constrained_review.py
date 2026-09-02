from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from .database import canonical_sense_key
from .dictionary import JMDictResolver
from .local_review import load_review_records


SENSE_PROMPT_VERSION = 1
SUPPORT_PROMPT_VERSION = 1
NONE_TEXT = "None of these / ambiguous"
PRECISION_TARGET = 0.995
_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LABEL_RESPONSE = re.compile(r"^\s*([A-Z])(?:[.)])?\s*$")


class LabelReviewer(Protocol):
    model_name: str

    def review(
        self, prompts: Sequence[str]
    ) -> Tuple[List[str], Mapping[str, Any]]:
        ...


@dataclass(frozen=True)
class SensePrompt:
    prompt: str
    label_to_sense: Mapping[str, Optional[str]]


def _sense_key(entry_id: int, sense_index: int) -> str:
    return canonical_sense_key(entry_id, sense_index, "", None)


def sense_options(
    card: Mapping[str, Any], resolver: Optional[JMDictResolver] = None
) -> List[Dict[str, str]]:
    resolver = resolver or JMDictResolver()
    return [
        {
            "sense_key": _sense_key(match.entry_id, match.sense_index),
            "gloss": match.gloss,
        }
        for match in resolver.sense_candidates(
            str(card.get("lemma") or ""),
            str(card.get("reading") or ""),
            str(card.get("part_of_speech") or ""),
            str(card.get("japanese") or ""),
        )
    ]


def build_sense_prompt(
    card: Mapping[str, Any], options: Sequence[Mapping[str, str]], round_index: int
) -> SensePrompt:
    if len(options) + 1 > len(_LABELS):
        raise ValueError("too many surviving senses for constrained labels")
    stable = json.dumps(
        {
            "candidate_key": card.get("candidate_key"),
            "learning_unit_key": card.get("learning_unit_key"),
            "japanese": card.get("japanese"),
            "round": int(round_index),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    seed = int(hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16], 16)
    shuffled = [dict(option) for option in options]
    random.Random(seed).shuffle(shuffled)
    label_to_sense: Dict[str, Optional[str]] = {}
    lines = []
    for index, option in enumerate(shuffled):
        label = _LABELS[index]
        label_to_sense[label] = str(option["sense_key"])
        lines.append(f"{label}. {option['gloss']}")
    none_label = _LABELS[len(shuffled)]
    label_to_sense[none_label] = None
    lines.append(f"{none_label}. {NONE_TEXT}")
    target = str(card.get("target_surface") or card.get("lemma") or "")
    prompt = "\n".join([
        "Choose the meaning of the marked Japanese word in this sentence.",
        "Reply with exactly one option letter and nothing else.",
        f"Sentence: {card.get('japanese') or ''}",
        f"Target: {target}",
        *lines,
    ])
    return SensePrompt(prompt=prompt, label_to_sense=label_to_sense)


def build_support_prompt(card: Mapping[str, Any], gloss: str) -> SensePrompt:
    mapping: Dict[str, Optional[str]] = {
        "A": "expressed", "B": "not_expressed", "C": None,
    }
    prompt = "\n".join([
        "Does the English subtitle explicitly express the supplied Japanese word meaning?",
        "Judge subtitle support only. Reply with exactly one letter.",
        f"Japanese: {card.get('japanese') or ''}",
        f"Target meaning: {gloss}",
        f"English subtitle: {card.get('english') or ''}",
        "A. Expressed",
        "B. Not expressed",
        "C. Ambiguous",
    ])
    return SensePrompt(prompt=prompt, label_to_sense=mapping)


def parse_label(raw: str, mapping: Mapping[str, Optional[str]]) -> Optional[str]:
    match = _LABEL_RESPONSE.fullmatch(str(raw or ""))
    if match is None or match.group(1) not in mapping:
        raise ValueError("invalid constrained label")
    return mapping[match.group(1)]


def _reviews_by_position(path: Path) -> Dict[int, Dict[str, Any]]:
    return {
        int(row["audit_position"]): row for row in load_review_records(path)
    }


def teacher_labels(
    contextual: Path, recoverability: Path, contextual_gloss: Path
) -> Dict[int, bool]:
    passes = [
        _reviews_by_position(contextual),
        _reviews_by_position(recoverability),
        _reviews_by_position(contextual_gloss),
    ]
    positions = set.intersection(*(set(values) for values in passes))
    return {
        position: all(
            values[position].get("verdict") == "correct" for values in passes
        )
        for position in positions
    }


def run_constrained_benchmark(
    cards: Sequence[Mapping[str, Any]],
    reviewer: LabelReviewer,
    teacher: Mapping[int, bool],
    *,
    resolver: Optional[JMDictResolver] = None,
    precision_target: float = PRECISION_TARGET,
) -> Dict[str, Any]:
    resolver = resolver or JMDictResolver()
    started = time.perf_counter()
    records = []
    counters: Counter[str] = Counter()
    aggregate_stats: Counter[str] = Counter()
    peak_memory = 0.0
    for card in cards:
        position = int(card["audit_position"])
        if position not in teacher:
            continue
        options = sense_options(card, resolver)
        expected = str(card.get("sense_key") or "")
        if expected not in {option["sense_key"] for option in options}:
            records.append({
                "audit_position": position,
                "teacher_accepted": bool(teacher[position]),
                "accepted": False,
                "reason": "selected_sense_not_in_candidates",
            })
            counters["abstained"] += 1
            continue
        prompts = [build_sense_prompt(card, options, value) for value in (1, 2)]
        raw, stats = reviewer.review([value.prompt for value in prompts])
        for name in ("prompt_tokens", "generation_tokens"):
            aggregate_stats[name] += int(stats.get(name, 0))
        for name in ("prompt_time", "generation_time"):
            aggregate_stats[name] += float(stats.get(name, 0.0))
        peak_memory = max(peak_memory, float(stats.get("peak_memory", 0.0)))
        try:
            votes = [
                parse_label(value, prompt.label_to_sense)
                for value, prompt in zip(raw, prompts)
            ]
        except ValueError:
            votes = []
        accepted = False
        reason = "sense_invalid_or_disagreed"
        support_raw = None
        if len(votes) == 2 and votes[0] is not None and votes[0] == votes[1]:
            if votes[0] != expected:
                reason = "different_sense"
            else:
                selected = next(
                    option for option in options
                    if option["sense_key"] == expected
                )
                support = build_support_prompt(card, selected["gloss"])
                support_values, support_stats = reviewer.review([support.prompt])
                support_raw = support_values[0] if support_values else ""
                for name in ("prompt_tokens", "generation_tokens"):
                    aggregate_stats[name] += int(support_stats.get(name, 0))
                for name in ("prompt_time", "generation_time"):
                    aggregate_stats[name] += float(support_stats.get(name, 0.0))
                peak_memory = max(
                    peak_memory, float(support_stats.get("peak_memory", 0.0))
                )
                try:
                    support_vote = parse_label(
                        support_raw, support.label_to_sense
                    )
                except ValueError:
                    support_vote = None
                accepted = support_vote == "expressed"
                reason = "accepted" if accepted else "subtitle_not_supported"
        teacher_accepted = bool(teacher[position])
        counters["accepted" if accepted else "abstained"] += 1
        if accepted and not teacher_accepted:
            counters["false_accepts"] += 1
        if accepted and teacher_accepted:
            counters["true_accepts"] += 1
        records.append({
            "audit_position": position,
            "teacher_accepted": teacher_accepted,
            "accepted": accepted,
            "reason": reason,
            "sense_votes": votes,
            "support_raw": support_raw,
        })
    evaluated = len(records)
    accepted_count = counters["accepted"]
    teacher_positive = sum(1 for row in records if row["teacher_accepted"])
    precision = (
        counters["true_accepts"] / accepted_count if accepted_count else 0.0
    )
    elapsed = time.perf_counter() - started
    return {
        "schema_version": 1,
        "model": reviewer.model_name,
        "prompt_versions": {
            "sense": SENSE_PROMPT_VERSION,
            "subtitle_support": SUPPORT_PROMPT_VERSION,
        },
        "summary": {
            "evaluated": evaluated,
            "accepted": accepted_count,
            "abstained": counters["abstained"],
            "teacher_accepted": teacher_positive,
            "true_accepts": counters["true_accepts"],
            "false_accepts": counters["false_accepts"],
            "accepted_precision": round(precision, 6),
            "acceptance_coverage": round(
                accepted_count / evaluated, 6
            ) if evaluated else 0.0,
            "teacher_positive_coverage": round(
                counters["true_accepts"] / teacher_positive, 6
            ) if teacher_positive else 0.0,
            "cards_per_second": round(evaluated / elapsed, 3) if elapsed else None,
            "peak_memory_gb": round(peak_memory, 3),
            "precision_target": precision_target,
            "adopt": bool(accepted_count and precision >= precision_target),
        },
        "inference": dict(aggregate_stats),
        "records": records,
    }


def run_constrained_dataset(
    dataset: Mapping[str, Any], reviewer: LabelReviewer, *,
    resolver: Optional[JMDictResolver] = None,
) -> Dict[str, Any]:
    """Run the frozen prompt/rule policy without consulting gold labels."""
    expected_versions = {
        "sense": SENSE_PROMPT_VERSION,
        "subtitle_support": SUPPORT_PROMPT_VERSION,
        "acceptance_policy": 1,
    }
    if dataset.get("prompt_versions") != expected_versions:
        raise ValueError("dataset prompt/rule versions do not match this runner")
    resolver = resolver or JMDictResolver()
    started = time.perf_counter()
    records: List[Dict[str, Any]] = []
    inference: Counter[str] = Counter()
    peak_memory = 0.0
    for split_rows in dataset.get("splits", {}).values():
        for case in split_rows:
            card = case["card"]
            position = int(card["audit_position"])
            result = run_constrained_benchmark(
                [card], reviewer, {position: True}, resolver=resolver,
            )
            row = dict(result["records"][0])
            row.pop("teacher_accepted", None)
            row["case_id"] = case["case_id"]
            row["abstained"] = not bool(row.get("accepted"))
            row["invalid_output"] = row.get("reason") == "sense_invalid_or_disagreed" and not row.get("sense_votes")
            records.append(row)
            for name, value in result.get("inference", {}).items():
                inference[name] += value
            peak_memory = max(
                peak_memory, float(result["summary"].get("peak_memory_gb") or 0.0)
            )
    elapsed = time.perf_counter() - started
    return {
        "schema_version": 1,
        "model": reviewer.model_name,
        "prompt_versions": expected_versions,
        "summary": {
            "evaluated": len(records),
            "accepted": sum(bool(row.get("accepted")) for row in records),
            "abstained": sum(bool(row.get("abstained")) for row in records),
            "cards_per_second": round(len(records) / elapsed, 3) if elapsed else None,
            "peak_memory_gb": round(peak_memory, 3),
        },
        "inference": dict(inference),
        "records": records,
    }


class MLXLabelReviewer:
    def __init__(
        self, model_name: str, *, max_tokens: int = 4,
        memory_limit_gb: float = 4.0,
    ) -> None:
        from huggingface_hub import snapshot_download

        from .inference_resources import InferenceResourceGuard

        self._resource_guard = InferenceResourceGuard(
            memory_limit_gb=memory_limit_gb
        )
        self._resource_guard.acquire()
        try:
            model_path = Path(model_name).expanduser()
            if not model_path.exists():
                model_path = Path(snapshot_download(model_name))
            self._resource_guard.validate_model_path(model_path)
            import mlx.core as mx
            self._resource_guard.configure_mlx(mx)
            from mlx_lm import batch_generate, load
            from mlx_lm.sample_utils import make_sampler
            model, tokenizer = load(str(model_path))
        except ImportError as error:  # pragma: no cover
            self._resource_guard.release()
            raise RuntimeError("Install the local-review extra") from error
        except Exception:
            self._resource_guard.release()
            raise
        self.model_name = model_name
        self.max_tokens = max_tokens
        self._batch_generate = batch_generate
        self._sampler = make_sampler(temp=0.0)
        self._mx = mx
        self._model, self._tokenizer = model, tokenizer

    def close(self) -> None:
        self._resource_guard.release(self._mx)

    def __del__(self) -> None:
        guard = getattr(self, "_resource_guard", None)
        if guard is not None:
            guard.release(getattr(self, "_mx", None))

    def review(
        self, prompts: Sequence[str]
    ) -> Tuple[List[str], Mapping[str, Any]]:
        encoded = [
            self._tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True,
                enable_thinking=False,
            )
            for prompt in prompts
        ]
        response = self._batch_generate(
            self._model,
            self._tokenizer,
            encoded,
            max_tokens=self.max_tokens,
            max_kv_size=1024,
            sampler=self._sampler,
            verbose=False,
        )
        stats = response.stats
        return list(response.texts), {
            "prompt_tokens": stats.prompt_tokens,
            "generation_tokens": stats.generation_tokens,
            "prompt_time": stats.prompt_time,
            "generation_time": stats.generation_time,
            "peak_memory": stats.peak_memory,
        }
