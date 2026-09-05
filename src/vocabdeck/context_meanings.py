"""Conservative occurrence-level accounting; ambiguity is not component mastery."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

CONTEXT_MEANINGS_VERSION = 1
UNRESOLVED_PREFIX = "unresolved-context:"


def context_meaning_issues(card: Mapping) -> list:
    """New artifacts fail closed; legacy artifacts keep their original policy."""
    if "context_meanings_version" not in card and "context_meaning_dependencies" not in card:
        return []
    deps = card.get("context_meaning_dependencies")
    if card.get("context_meanings_version") != CONTEXT_MEANINGS_VERSION or not isinstance(deps, list):
        return ["invalid_context_meaning_metadata"]
    if any(not isinstance(item, Mapping)
           or not isinstance(item.get("learning_unit_key"), str)
           or not isinstance(item.get("start"), int)
           or not isinstance(item.get("end"), int)
           or not 0 <= item["start"] < item["end"] <= len(str(card.get("japanese") or ""))
           for item in deps):
        return ["invalid_context_meaning_metadata"]
    keys = {item["learning_unit_key"] for item in deps}
    if keys != set(card.get("context_learning_unit_keys") or []):
        return ["inconsistent_context_meaning_keys"]
    issues = []
    if any(item.get("resolution") == "unresolved_expression"
           or item["learning_unit_key"].startswith(UNRESOLVED_PREFIX) for item in deps):
        issues.append("unresolved_context_expression")
    target = card.get("learning_unit_key")
    start = card.get("target_lexical_start", card.get("target_start"))
    end = card.get("target_lexical_end", card.get("target_end"))
    if not any(item["learning_unit_key"] == target
               and item["start"] == start and item["end"] == end for item in deps):
        issues.append("target_context_meaning_mismatch")
    return issues


def resolve_dependency_spans(
    japanese: str,
    english: str,
    dependencies: Sequence[Mapping],
    analyses: Sequence[Mapping],
) -> list:
    """Overlay unresolved expression spans on persisted/resolved dependencies.

    Accepted atomic spans supersede nested alternative analyses. Other
    overlapping uncertainties form one connected span, never two invented
    vocabulary items. Partial overlap includes the full affected dependency.
    IDs describe an unresolved occurrence, not a teachable dictionary meaning.
    """
    deps = [dict(item) for item in dependencies]
    unresolved = []
    for analysis in analyses:
        start, end = int(analysis["start_char"]), int(analysis["end_char"])
        if not 0 <= start < end <= len(japanese):
            raise ValueError("expression dependency has invalid offsets")
        if analysis["decision"] in {"expression", "components"}:
            continue
        if any(
            dep.get("resolution") == "expression"
            and int(dep["start"]) <= start and end <= int(dep["end"])
            for dep in deps
        ):
            continue
        unresolved.append({
            "start": start, "end": end, "analyses": [dict(analysis)],
        })

    # Close spans over touched lexical units, then merge overlapping spans.
    # Iterate because a union can touch another partially overlapping unit.
    changed = True
    while changed:
        changed = False
        for span in unresolved:
            for dep in deps:
                if span["start"] < dep["end"] and dep["start"] < span["end"]:
                    start, end = min(span["start"], dep["start"]), max(span["end"], dep["end"])
                    changed |= (start, end) != (span["start"], span["end"])
                    span.update(start=start, end=end)
        merged = []
        for span in sorted(unresolved, key=lambda value: (value["start"], value["end"])):
            if merged and span["start"] < merged[-1]["end"]:
                previous = merged[-1]
                previous["end"] = max(previous["end"], span["end"])
                previous["analyses"].extend(span["analyses"])
                changed = True
            else:
                merged.append(span)
        unresolved = merged

    result = [dep for dep in deps if not any(
        span["start"] < dep["end"] and dep["start"] < span["end"]
        for span in unresolved
    )]
    for span in unresolved:
        start, end = span["start"], span["end"]
        fingerprint = json.dumps(
            [CONTEXT_MEANINGS_VERSION, japanese, english, start, end],
            ensure_ascii=False, separators=(",", ":"),
        )
        result.append({
            "start": start, "end": end, "surface": japanese[start:end],
            "learning_unit_key": UNRESOLVED_PREFIX + hashlib.sha256(
                fingerprint.encode("utf-8")
            ).hexdigest()[:24],
            "resolution": "unresolved_expression", "teachable": False,
            "expression_evidence": span["analyses"],
        })
    return sorted(result, key=lambda value: (value["start"], value["end"]))
