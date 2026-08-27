from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Protocol, Sequence, Tuple

from .audit import READING_CHECK_POS
from .local_review import card_fingerprint


REQUIRED_DETERMINISTIC_CRITERIA = (
    "translation_available",
    "translation_alignment",
    "definition_available",
    "contextual_interpretation",
    "gloss_support",
    "expression_interpretation",
    "unique_example",
)
REQUIRED_INFORMATIONAL_CRITERIA = ("context_difficulty",)
PEDAGOGICAL_FINDINGS = {"harder_unknown_context"}
VALIDATION_STATUSES = {"accepted", "rejected", "abstained"}
_HAS_KANJI = re.compile(r"[\u3400-\u9fff]")
_ENGLISH_TOKEN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")


def _learning_unit_key(card: Mapping[str, Any]) -> str:
    value = card.get("learning_unit_key")
    if value:
        return str(value)
    return f"lexeme:{int(card['lexeme_id'])}"


def _context_learning_units(card: Mapping[str, Any]) -> Optional[set[str]]:
    values = card.get("context_learning_unit_keys")
    if isinstance(values, list):
        return {str(value) for value in values}
    legacy = card.get("context_lexeme_ids")
    if isinstance(legacy, list):
        return {f"lexeme:{int(value)}" for value in legacy}
    return None


def _initial_known_learning_units(
    card: Mapping[str, Any]
) -> Optional[set[str]]:
    values = card.get("initial_known_context_learning_unit_keys")
    if isinstance(values, list):
        return {str(value) for value in values}
    legacy = card.get("initial_known_context_lexeme_ids")
    if isinstance(legacy, list):
        return {f"lexeme:{int(value)}" for value in legacy}
    return None


@dataclass(frozen=True)
class ValidationResult:
    validator: str
    status: str
    reason_codes: Tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in VALIDATION_STATUSES:
            raise ValueError(f"unsupported validation status: {self.status!r}")
        if self.status == "accepted" and self.reason_codes:
            raise ValueError("accepted validation results cannot contain reasons")
        if self.status != "accepted" and not self.reason_codes:
            raise ValueError("non-accepted validation results require a reason")

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["reason_codes"] = list(self.reason_codes)
        return value


class CardValidator(Protocol):
    name: str

    def validate(self, card: Mapping[str, Any]) -> ValidationResult:
        ...


class DeterministicCardValidator:
    """Fail closed on incomplete, flagged, or internally inconsistent audits."""

    name = "deterministic"

    def validate(self, card: Mapping[str, Any]) -> ValidationResult:
        japanese = str(card.get("japanese") or "")
        english = str(card.get("english") or "").strip()
        gloss = str(card.get("gloss") or "").strip()
        target = str(card.get("target_surface") or "")
        content_words = int(
            (card.get("example_progression") or {}).get("content_words", 0)
        )
        start = card.get("target_start")
        end = card.get("target_end")
        structural_reasons: List[str] = []
        if not english:
            structural_reasons.append("missing_translation")
        elif len(_ENGLISH_TOKEN.findall(english)) > max(
            12, content_words * 6
        ):
            structural_reasons.append("excess_translation_scope")
        if not gloss:
            structural_reasons.append("missing_definition")
        if not (
            target
            and isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(japanese)
            and japanese[start:end] == target
        ):
            structural_reasons.append("invalid_target_span")
        elif content_words == 1:
            outside_target = japanese[:start] + japanese[end:]
            if _HAS_KANJI.search(outside_target):
                structural_reasons.append("untracked_kanji_context")
        if structural_reasons:
            return ValidationResult(
                self.name, "rejected", tuple(sorted(set(structural_reasons)))
            )

        finding_codes = sorted({
            str(finding.get("code") or "unknown_audit_finding")
            for finding in card.get("audit_findings", [])
            if str(finding.get("code") or "") not in PEDAGOGICAL_FINDINGS
        })
        if finding_codes:
            return ValidationResult(
                self.name,
                "rejected",
                tuple(f"audit:{code}" for code in finding_codes),
            )

        criteria = {
            str(criterion.get("code") or ""): str(
                criterion.get("status") or ""
            )
            for criterion in card.get("audit_criteria", [])
        }
        missing = [
            code for code in REQUIRED_DETERMINISTIC_CRITERIA
            if code not in criteria
        ]
        missing.extend(
            code for code in REQUIRED_INFORMATIONAL_CRITERIA
            if code not in criteria
        )
        if "contextual_reading" not in criteria:
            missing.append("contextual_reading")
        if missing:
            return ValidationResult(
                self.name,
                "abstained",
                tuple(f"missing_criterion:{code}" for code in sorted(missing)),
            )

        unresolved = [
            code for code in REQUIRED_DETERMINISTIC_CRITERIA
            if criteria[code] != "passed"
        ]
        reading_status = criteria["contextual_reading"]
        part_of_speech = str(card.get("part_of_speech") or "")
        if reading_status == "flagged":
            unresolved.append("contextual_reading")
        elif part_of_speech in READING_CHECK_POS and reading_status != "passed":
            unresolved.append("contextual_reading")
        elif reading_status not in {"passed", "not_checked"}:
            unresolved.append("contextual_reading")
        if unresolved:
            return ValidationResult(
                self.name,
                "abstained",
                tuple(f"unresolved_criterion:{code}" for code in sorted(set(unresolved))),
            )
        return ValidationResult(self.name, "accepted", ())


class RecordedReviewValidator:
    """Validate cards from a blind, fingerprinted model-review pass."""

    def __init__(
        self,
        review_pass: str,
        reviews: Sequence[Mapping[str, Any]],
    ) -> None:
        if review_pass not in {
            "contextual", "critic", "recoverability", "contextual_gloss",
        }:
            raise ValueError(f"unsupported review pass: {review_pass!r}")
        self.review_pass = review_pass
        self.name = f"llm:{review_pass}"
        self._reviews = {
            int(review["audit_position"]): dict(review) for review in reviews
        }

    def validate(self, card: Mapping[str, Any]) -> ValidationResult:
        position = int(card["audit_position"])
        review = self._reviews.get(position)
        if review is None:
            return ValidationResult(
                self.name, "abstained", (f"missing_{self.review_pass}_review",)
            )
        if str(review.get("review_pass") or "") != self.review_pass:
            return ValidationResult(
                self.name, "abstained", ("review_pass_mismatch",)
            )
        expected = card_fingerprint(card, review_pass=self.review_pass)
        if review.get("card_fingerprint") != expected:
            return ValidationResult(
                self.name, "abstained", ("stale_card_fingerprint",)
            )
        verdict = str(review.get("verdict") or "")
        reason = str(review.get("reason_code") or "invalid_output")
        if verdict == "correct" and reason == "supported":
            return ValidationResult(self.name, "accepted", ())
        if verdict == "incorrect":
            return ValidationResult(
                self.name, "rejected", (f"{self.review_pass}:{reason}",)
            )
        return ValidationResult(
            self.name, "abstained", (f"{self.review_pass}:{reason}",)
        )


class UnanimousCardValidator:
    """Accept only when every independent validator explicitly accepts."""

    def __init__(self, validators: Sequence[CardValidator]) -> None:
        if not validators:
            raise ValueError("at least one validator is required")
        self.validators = list(validators)

    def validate(self, card: Mapping[str, Any]) -> Dict[str, Any]:
        stages: List[ValidationResult] = []
        for validator in self.validators:
            result = validator.validate(card)
            stages.append(result)
            if result.status != "accepted":
                return {
                    "status": result.status,
                    "failed_stage": result.validator,
                    "reason_codes": list(result.reason_codes),
                    "stages": [stage.as_dict() for stage in stages],
                }
        return {
            "status": "accepted",
            "failed_stage": None,
            "reason_codes": [],
            "stages": [stage.as_dict() for stage in stages],
        }


def validate_cards(
    cards: Sequence[Mapping[str, Any]], validator: UnanimousCardValidator
) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {
        "accepted": [], "rejected": [], "abstained": [],
    }
    for card in cards:
        decision = validator.validate(card)
        groups[decision["status"]].append({
            "audit_position": int(card["audit_position"]),
            "lexeme_key": str(card.get("lexeme_key") or ""),
            "lemma": str(card.get("lemma") or ""),
            "decision": decision,
        })
    return {
        **groups,
        "summary": {status: len(rows) for status, rows in groups.items()},
    }


def write_validation_report(report: Mapping[str, Any], output: Path) -> Path:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def plan_review_frontier(
    cards: Sequence[Mapping[str, Any]],
    *,
    selected_cards: Sequence[Mapping[str, Any]] = (),
    reviews_by_pass: Optional[
        Mapping[str, Sequence[Mapping[str, Any]]]
    ] = None,
    limit: int = 40,
    frontier_size: int = 100,
    zero_unknown_through: int = 20,
    one_unknown_through: int = 200,
    later_unknown_limit: int = 2,
    harder_unknown_tolerance: float = 2.0,
) -> Dict[str, Any]:
    """Choose currently teachable occurrences that still need model review."""
    from .progression import allowed_unknown_context_words

    if limit < 1:
        raise ValueError("review limit must be positive")
    if frontier_size < 1:
        raise ValueError("frontier size must be positive")
    reviews_by_pass = reviews_by_pass or {}
    review_passes = ("contextual", "recoverability", "contextual_gloss")
    validators = {
        review_pass: RecordedReviewValidator(
            review_pass, reviews_by_pass.get(review_pass, ())
        )
        for review_pass in review_passes
    }
    grouped: Dict[int, List[Mapping[str, Any]]] = {}
    for card in cards:
        position = int(
            card.get("curriculum_position") or card["audit_position"]
        )
        grouped.setdefault(position, []).append(card)
    for candidates in grouped.values():
        candidates.sort(key=lambda card: (
            int(card.get("candidate_position") or 1),
            float(
                (card.get("example_progression") or {}).get(
                    "selection_score", 0.0
                )
            ),
            int(card.get("sentence_id") or 0),
        ))

    selected_target_ids = {
        _learning_unit_key(card) for card in selected_cards
    }
    used_sentence_ids = {
        int(card.get("sentence_id") or 0) for card in selected_cards
    }
    known_ids = {
        value
        for card in cards
        for value in (_initial_known_learning_units(card) or set())
    } | selected_target_ids
    lexical_difficulties = {
        _learning_unit_key(candidates[0]): float(
            candidates[0].get("difficulty_score") or 0.0
        )
        for candidates in grouped.values()
    }
    teaching_position = len(selected_cards) + 1
    allowance = allowed_unknown_context_words(
        teaching_position,
        zero_unknown_through=zero_unknown_through,
        one_unknown_through=one_unknown_through,
        later_limit=later_unknown_limit,
    )
    remaining_positions = [
        position for position in sorted(grouped)
        if _learning_unit_key(grouped[position][0]) not in selected_target_ids
    ]

    def candidates_in(positions: Sequence[int]):
        planned = []
        for curriculum_position in positions:
            for card in grouped[curriculum_position]:
                if DeterministicCardValidator().validate(card).status != "accepted":
                    continue
                sentence_id = int(card.get("sentence_id") or 0)
                raw_context_ids = _context_learning_units(card)
                initial_context_ids = _initial_known_learning_units(card)
                if (
                    sentence_id in used_sentence_ids
                    or raw_context_ids is None
                    or initial_context_ids is None
                ):
                    continue
                target_id = _learning_unit_key(card)
                unknown_ids = (
                    raw_context_ids
                    - {target_id}
                    - known_ids
                )
                if len(unknown_ids) > allowance:
                    continue
                target_difficulty = lexical_difficulties[target_id]
                if any(
                    value not in lexical_difficulties
                    or lexical_difficulties[value]
                    > target_difficulty + harder_unknown_tolerance
                    for value in unknown_ids
                ):
                    continue
                review_results = {
                    review_pass: validator.validate(card)
                    for review_pass, validator in validators.items()
                }
                if any(
                    result.status == "rejected" or (
                        result.status == "abstained"
                        and not all(
                            reason.startswith("missing_")
                            and reason.endswith("_review")
                            for reason in result.reason_codes
                        )
                    )
                    for result in review_results.values()
                ):
                    continue
                missing_passes = [
                    review_pass for review_pass, result in review_results.items()
                    if result.status != "accepted"
                ]
                if not missing_passes:
                    # It is already fully reviewed; the main selector, not this
                    # planner, owns materializing it into the teaching sequence.
                    continue
                example_value = float(
                    (card.get("example_progression") or {}).get(
                        "selection_score", 0.0
                    )
                )
                planned.append((
                    len(unknown_ids), curriculum_position, example_value,
                    int(card.get("candidate_position") or 1), sentence_id,
                    card, missing_passes, sorted(unknown_ids),
                ))
        return planned

    frontier = remaining_positions[:frontier_size]
    planned = candidates_in(frontier)
    frontier_expanded = False
    if not planned and len(frontier) < len(remaining_positions):
        planned = candidates_in(remaining_positions[frontier_size:])
        frontier_expanded = bool(planned)
    planned.sort(key=lambda item: item[:5])
    # Review one occurrence per target in a round. Rejected occurrences can be
    # replaced by the next candidate in the following resumable round.
    chosen = []
    seen_targets = set()
    for plan in planned:
        card = plan[5]
        target_id = _learning_unit_key(card)
        if target_id in seen_targets:
            continue
        materialized = dict(card)
        materialized["review_planning"] = {
            "teaching_position": teaching_position,
            "unknown_allowance": allowance,
            "unknown_context_learning_unit_keys": plan[7],
            "missing_review_passes": plan[6],
            "frontier_expanded": frontier_expanded,
        }
        chosen.append(materialized)
        seen_targets.add(target_id)
        if len(chosen) >= limit:
            break
    return {
        "cards": chosen,
        "summary": {
            "teaching_position": teaching_position,
            "known_targets": len(selected_target_ids),
            "unknown_allowance": allowance,
            "frontier_size": frontier_size,
            "frontier_expanded": frontier_expanded,
            "planned_reviews": len(chosen),
            "remaining_targets": len(remaining_positions),
        },
    }


def select_validated_curriculum(
    cards: Sequence[Mapping[str, Any]],
    validation_report: Mapping[str, Any],
    *,
    frontier_size: int = 100,
    zero_unknown_through: int = 20,
    one_unknown_through: int = 200,
    later_unknown_limit: int = 2,
    harder_unknown_tolerance: float = 2.0,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Schedule approved cards from a lexical frontier and sentence dependencies.

    Lexical ranking defines the candidate pool and local priority, while the
    learner's simulated known set determines which validated occurrence can be
    taught next. Missing dependency metadata fails closed.
    """
    from .progression import allowed_unknown_context_words

    if frontier_size < 1:
        raise ValueError("frontier size must be positive")
    if limit is not None and limit < 1:
        raise ValueError("selection limit must be positive")
    decisions = {
        int(item["audit_position"]): dict(item["decision"])
        for status in ("accepted", "rejected", "abstained")
        for item in validation_report.get(status, [])
    }
    grouped: Dict[int, List[Mapping[str, Any]]] = {}
    for card in cards:
        position = int(
            card.get("curriculum_position") or card["audit_position"]
        )
        grouped.setdefault(position, []).append(card)

    for candidates in grouped.values():
        candidates.sort(key=lambda card: (
            int(card.get("candidate_position") or 1),
            float(
                (card.get("example_progression") or {}).get(
                    "selection_score", 0.0
                )
            ),
            int(card.get("sentence_id") or 0),
        ))

    lexical_difficulties = {
        _learning_unit_key(candidates[0]): float(
            candidates[0].get("difficulty_score") or 0.0
        )
        for candidates in grouped.values()
    }
    known_ids = {
        value
        for card in cards
        for value in (_initial_known_learning_units(card) or set())
    }
    remaining = sorted(grouped)
    selected: List[Dict[str, Any]] = []
    used_sentence_ids = set()
    frontier_expansions = 0

    def best_plan(positions: Sequence[int], teaching_position: int):
        allowance = allowed_unknown_context_words(
            teaching_position,
            zero_unknown_through=zero_unknown_through,
            one_unknown_through=one_unknown_through,
            later_limit=later_unknown_limit,
        )
        plans = []
        for curriculum_position in positions:
            for card in grouped[curriculum_position]:
                decision = decisions.get(int(card["audit_position"]))
                sentence_id = int(card.get("sentence_id") or 0)
                raw_context_ids = _context_learning_units(card)
                raw_initial_known_ids = _initial_known_learning_units(card)
                if (
                    decision is None
                    or decision.get("status") != "accepted"
                    or sentence_id in used_sentence_ids
                    or raw_context_ids is None
                    or raw_initial_known_ids is None
                ):
                    continue
                target_id = _learning_unit_key(card)
                other_ids = raw_context_ids - {target_id}
                unknown_ids = other_ids - known_ids
                if len(unknown_ids) > allowance:
                    continue
                target_difficulty = lexical_difficulties[target_id]
                if any(
                    lexeme_id not in lexical_difficulties
                    or lexical_difficulties[lexeme_id]
                    > target_difficulty + harder_unknown_tolerance
                    for lexeme_id in unknown_ids
                ):
                    continue
                example_value = float(
                    (card.get("example_progression") or {}).get(
                        "selection_score", 0.0
                    )
                )
                plans.append((
                    len(unknown_ids), curriculum_position, example_value,
                    int(card.get("candidate_position") or 1), sentence_id,
                    card, decision, sorted(unknown_ids), allowance,
                ))
        return min(plans, default=None, key=lambda plan: plan[:5])

    while remaining and (limit is None or len(selected) < limit):
        teaching_position = len(selected) + 1
        frontier = remaining[:frontier_size]
        plan = best_plan(frontier, teaching_position)
        expanded = False
        if plan is None and len(frontier) < len(remaining):
            # Expand only when every nearby target is currently blocked. A
            # farther teachable word may unlock dependencies in the frontier.
            plan = best_plan(remaining[frontier_size:], teaching_position)
            expanded = plan is not None
        if plan is None:
            break
        (
            _, curriculum_position, _, _, _, card, decision, unknown_ids,
            allowance,
        ) = plan
        materialized = dict(card)
        materialized["validation"] = decision
        materialized["clean_position"] = teaching_position
        materialized["teaching_position"] = teaching_position
        materialized["lexical_position"] = curriculum_position
        materialized["scheduling"] = {
            "unknown_allowance": allowance,
            "unknown_context_learning_unit_keys": unknown_ids,
            "unknown_context_words": len(unknown_ids),
            "frontier_size": frontier_size,
            "frontier_expanded": expanded,
        }
        progression = dict(materialized.get("example_progression") or {})
        progression["position"] = teaching_position
        progression["unknown_other_words"] = len(unknown_ids)
        progression["known_other_words"] = max(
            0,
            len((_context_learning_units(materialized) or set()) - {
                _learning_unit_key(card)
            })
            - len(unknown_ids),
        )
        materialized["example_progression"] = progression
        selected.append(materialized)
        used_sentence_ids.add(int(card.get("sentence_id") or 0))
        known_ids.add(_learning_unit_key(card))
        remaining.remove(curriculum_position)
        if expanded:
            frontier_expansions += 1

    deferred: List[Dict[str, Any]] = []
    final_position = len(selected) + 1
    final_allowance = allowed_unknown_context_words(
        final_position,
        zero_unknown_through=zero_unknown_through,
        one_unknown_through=one_unknown_through,
        later_limit=later_unknown_limit,
    )
    for curriculum_position in remaining:
        candidates = grouped[curriculum_position]
        statuses = Counter(
            str(decisions.get(int(card["audit_position"]), {}).get(
                "status", "not_reviewed"
            ))
            for card in candidates
        )
        accepted_candidates = [
            card for card in candidates
            if decisions.get(int(card["audit_position"]), {}).get("status")
            == "accepted"
        ]
        blockers = set()
        minimum_unknown = None
        for card in accepted_candidates:
            raw_context_ids = _context_learning_units(card)
            if (
                raw_context_ids is None
                or _initial_known_learning_units(card) is None
            ):
                blockers.add("missing_context_metadata")
                continue
            target_id = _learning_unit_key(card)
            unknown_ids = (
                raw_context_ids - {target_id} - known_ids
            )
            minimum_unknown = (
                len(unknown_ids) if minimum_unknown is None
                else min(minimum_unknown, len(unknown_ids))
            )
            if len(unknown_ids) > final_allowance:
                blockers.add("unknown_context_limit")
            if any(
                value not in lexical_difficulties
                for value in unknown_ids
            ):
                blockers.add("unscored_unknown_context")
            if any(
                value in lexical_difficulties
                and lexical_difficulties[value]
                > lexical_difficulties[target_id] + harder_unknown_tolerance
                for value in unknown_ids
            ):
                blockers.add("harder_unknown_context")
        if not accepted_candidates:
            blockers.add("no_validated_occurrence")
        first = candidates[0]
        deferred.append({
            "curriculum_position": curriculum_position,
            "lexeme_key": str(first.get("lexeme_key") or ""),
            "sense_key": str(first.get("sense_key") or ""),
            "learning_unit_key": str(
                first.get("learning_unit_key") or ""
            ),
            "lemma": str(first.get("lemma") or ""),
            "candidate_statuses": dict(sorted(statuses.items())),
            "blockers": sorted(blockers),
            "minimum_unknown_context_words": minimum_unknown,
        })
    return {
        "accepted": selected,
        "deferred": deferred,
        "summary": {
            "curriculum_targets": len(grouped),
            "accepted": len(selected),
            "deferred": len(deferred),
            "frontier_size": frontier_size,
            "frontier_expansions": frontier_expansions,
            "zero_unknown_through": zero_unknown_through,
            "one_unknown_through": one_unknown_through,
            "later_unknown_limit": later_unknown_limit,
            "requested_limit": limit,
            "complete": limit is None or len(selected) == limit,
        },
    }
