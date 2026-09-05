"""Read-only diagnostics for an existing curriculum, not a new selector."""
from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
import math
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .progression import allowed_unknown_context_words
from .validation import (
    DeterministicCardValidator, _context_learning_units,
    _initial_known_learning_units, _learning_unit_key,
)


PRIMARY_ORDER = (
    "selected", "alternative_to_selected_target", "deterministic_rejected",
    "deterministic_abstained", "validation_rejected", "validation_abstained",
    "missing_context_metadata", "sentence_reserved", "unknown_context_limit",
    "unscored_unknown_context", "harder_unknown_context",
    "accepted_not_selected", "eligible_unreviewed",
)


def build_candidate_accounting(
    cards: Sequence[Mapping[str, Any]],
    validation: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    harder_unknown_tolerance: Optional[float],
) -> dict:
    """Explain every input row against the *final* simulated learned set.

    Primary dispositions are exclusive, but independent gate evidence is kept.
    No claims are made about historical search visits or actual learner mastery.
    Legacy validation reports identify candidates by position and lexeme only;
    that limitation is explicit rather than pretending hashes prove provenance.
    """
    if harder_unknown_tolerance is not None and (
        not math.isfinite(harder_unknown_tolerance) or harder_unknown_tolerance < 0
    ):
        raise ValueError("harder unknown tolerance must be nonnegative or None")
    by_position = {}
    for card in cards:
        position = int(card["audit_position"])
        if position in by_position:
            raise ValueError(f"duplicate candidate audit_position: {position}")
        by_position[position] = card

    decisions = {}
    for status in ("accepted", "rejected", "abstained"):
        for item in validation.get(status, []):
            position = int(item["audit_position"])
            if position not in by_position or position in decisions:
                raise ValueError(f"unknown or duplicate validation position: {position}")
            card = by_position[position]
            for field in ("lexeme_key", "lemma", "candidate_key", "learning_unit_key"):
                if field in item and item[field] != card.get(field):
                    raise ValueError(f"validation identity mismatch at {position}: {field}")
            decision = item["decision"]
            if decision.get("status") != status:
                raise ValueError(f"validation status mismatch at {position}")
            decisions[position] = decision

    selected = selection.get("accepted", [])
    selected_positions, learned, owners = {}, {}, {}
    for teaching_position, card in enumerate(selected, 1):
        position = int(card["audit_position"])
        original = by_position.get(position)
        # Scheduling fields can change; the actual occurrence cannot.
        if original is None or any(
            card.get(field) != original.get(field)
            for field in (
                "candidate_key", "learning_unit_key", "sentence_id", "japanese",
                "english", "gloss", "reading", "target_start", "target_end",
            )
        ):
            raise ValueError(f"selected occurrence mismatch at {position}")
        if decisions.get(position, {}).get("status") != "accepted":
            raise ValueError(f"selected candidate has no accepted validation: {position}")
        unit = _learning_unit_key(card)
        sentence = int(card.get("sentence_id") or 0)
        if position in selected_positions or sentence in owners or unit in learned:
            raise ValueError("selection repeats a candidate, sentence, or learning unit")
        owner = {
            "teaching_position": teaching_position, "audit_position": position,
            "learning_unit_key": unit, "lemma": str(card.get("lemma") or ""),
        }
        selected_positions[position] = owner
        learned[unit] = owner
        owners[sentence] = owner

    summary = selection.get("summary", {})
    policy = {
        "zero_unknown_through": int(summary.get("zero_unknown_through", 20)),
        "one_unknown_through": int(summary.get("one_unknown_through", 200)),
        "later_unknown_limit": int(summary.get("later_unknown_limit", 2)),
        "harder_unknown_tolerance": harder_unknown_tolerance,
    }
    if "harder_unknown_tolerance" in summary and (
        summary["harder_unknown_tolerance"] != harder_unknown_tolerance
    ):
        raise ValueError("harder unknown tolerance differs from selection policy")
    allowance = allowed_unknown_context_words(
        len(selected) + 1,
        zero_unknown_through=policy["zero_unknown_through"],
        one_unknown_through=policy["one_unknown_through"],
        later_limit=policy["later_unknown_limit"],
    )
    known = set(learned) | {
        unit for card in cards
        for unit in (_initial_known_learning_units(card) or set())
    }
    difficulties, labels = {}, {}
    for card in cards:
        unit = _learning_unit_key(card)
        difficulties.setdefault(unit, float(card.get("difficulty_score") or 0.0))
        labels.setdefault(unit, {
            "learning_unit_key": unit, "lemma": str(card.get("lemma") or ""),
            "reading": str(card.get("reading") or ""),
            "gloss": str(card.get("gloss") or ""),
        })

    rows, grouped = [], defaultdict(list)
    validator = DeterministicCardValidator()
    for position, card in sorted(by_position.items()):
        unit = _learning_unit_key(card)
        sentence = int(card.get("sentence_id") or 0)
        deterministic = validator.validate(card)
        decision = decisions.get(position)
        review_stages = [
            stage for stage in (decision or {}).get("stages", [])
            if str(stage.get("validator", "")).startswith("llm:")
        ]
        review_status = "not_reviewed"
        if review_stages:
            statuses = {stage["status"] for stage in review_stages}
            review_status = next(
                status for status in ("rejected", "abstained", "accepted")
                if status in statuses
            )
        elif decision and not decision.get("stages"):
            review_status = "provenance_unavailable"

        context = _context_learning_units(card)
        missing = context is None or _initial_known_learning_units(card) is None
        unknown = sorted((context or set()) - {unit} - known)
        unscored = sorted(set(unknown) - difficulties.keys())
        gaps = [difficulties[value] - difficulties[unit] for value in unknown
                if value in difficulties]
        hardest_gap = max(gaps, default=0.0)
        owner = owners.get(sentence)
        blockers = []
        if missing:
            blockers.append("missing_context_metadata")
        if owner and position not in selected_positions:
            blockers.append("sentence_reserved")
        if not missing:
            if len(unknown) > allowance:
                blockers.append("unknown_context_limit")
            if unscored:
                blockers.append("unscored_unknown_context")
            if harder_unknown_tolerance is not None and hardest_gap > harder_unknown_tolerance:
                blockers.append("harder_unknown_context")

        if position in selected_positions:
            primary = "selected"
        elif unit in learned:
            primary = "alternative_to_selected_target"
        elif deterministic.status != "accepted":
            primary = "deterministic_" + deterministic.status
        elif decision and decision["status"] != "accepted":
            # This is a recorded *validation* outcome; stage provenance below
            # distinguishes a model failure from any other validator.
            primary = "validation_" + decision["status"]
        elif blockers:
            primary = blockers[0]
        elif decision:
            primary = "accepted_not_selected"
        else:
            primary = "eligible_unreviewed"
        row = {
            "audit_position": position, "candidate_key": card.get("candidate_key"),
            **labels[unit], "gloss": str(card.get("gloss") or ""),
            "reading": str(card.get("reading") or ""), "sentence_id": sentence,
            "episode": card.get("episode"), "japanese": str(card.get("japanese") or ""),
            "english": str(card.get("english") or ""), "primary_disposition": primary,
            "deterministic": deterministic.as_dict(),
            "recorded_validation": decision,
            "model_review_status": review_status,
            "selected_at": selected_positions.get(position),
            "target_learned_at": learned.get(unit),
            "sentence_reserved_by": owner,
            "final_state": {
                "blockers": blockers, "unknown_context_words": None if missing else len(unknown),
                "unknown_dependencies": [labels.get(value, {
                    "learning_unit_key": value, "lemma": None,
                }) for value in unknown],
                "unscored_dependencies": unscored,
                "hardest_scored_unknown_gap": hardest_gap,
                "unknown_allowance": allowance,
            },
        }
        rows.append(row)
        grouped[unit].append(row)

    targets = []
    for unit, candidates in grouped.items():
        targets.append({
            **labels[unit], "selected_at": learned.get(unit),
            "candidate_count": len(candidates),
            "distinct_sentences": len({row["sentence_id"] for row in candidates}),
            "primary_counts": dict(sorted(Counter(row["primary_disposition"] for row in candidates).items())),
            "model_review_counts": dict(sorted(Counter(row["model_review_status"] for row in candidates).items())),
            "audit_positions": [row["audit_position"] for row in candidates],
        })
    primary_counts = dict(sorted(Counter(row["primary_disposition"] for row in rows).items()))
    return {
        "schema_version": 1,
        "interpretation": [
            "Final-state snapshot at the next teaching position; not a historical search trace.",
            "Unknowns use stored meaning identities, which may contain unresolved expression/sense errors.",
            "Primary categories are exclusive in the documented precedence; independent evidence may overlap.",
            "Not reviewed does not mean rejected. A recorded model acceptance is not human-verified correctness.",
            "Legacy validation joins use audit position and available identity fields, not full review fingerprints.",
            "Artifact hashes identify the supplied files, not proof that legacy reviews match every prompt field.",
            "This report does not validate audio or alter any curriculum decision.",
            "Counts cover the supplied candidate pool, not candidates excluded before the pool was built.",
        ],
        "primary_precedence": list(PRIMARY_ORDER), "policy": policy,
        "summary": {
            "candidate_pairs": len(rows),
            "distinct_sentences": len({row["sentence_id"] for row in rows}),
            "learning_units": len(targets), "selected_cards": len(selected),
            "recorded_validation_decisions": len(decisions),
            "next_teaching_position": len(selected) + 1,
            "primary_counts": primary_counts,
            "primary_counts_reconcile": sum(primary_counts.values()) == len(rows),
            "model_review_counts": dict(sorted(Counter(row["model_review_status"] for row in rows).items())),
            "final_blocker_counts_overlapping": dict(sorted(Counter(
                blocker for row in rows for blocker in row["final_state"]["blockers"]
            ).items())),
        },
        "targets": targets, "candidates": rows,
    }


def render_candidate_accounting(report: Mapping[str, Any], output: Path) -> Path:
    """Standalone, escaped HTML; target-level filtering avoids a giant open table."""
    import json

    def counts(values):
        return "; ".join(f"{escape(str(key))}: {value}" for key, value in values.items())

    by_position = {row["audit_position"]: row for row in report["candidates"]}
    sections = []
    for target in report["targets"]:
        candidate_rows = []
        for position in target["audit_positions"]:
            row = by_position[position]
            state = row["final_state"]
            owner = row["sentence_reserved_by"]
            reservation = (
                f"Card {owner['teaching_position']}: {escape(owner['lemma'])}"
                if owner else "None"
            )
            unknowns = "; ".join(
                escape(f"{item.get('lemma') or '[unscored]'} — {item.get('gloss') or item['learning_unit_key']}")
                for item in state["unknown_dependencies"]
            ) or "None"
            evidence = escape(json.dumps({
                "deterministic": row["deterministic"],
                "recorded_validation": row["recorded_validation"],
                "final_state": state,
            }, ensure_ascii=False, indent=2))
            candidate_rows.append(
                f'<tr id="candidate-{position}"><td>#{position}<br>Sentence {row["sentence_id"]}</td>'
                f'<td>{escape(row["japanese"])}<br>{escape(row["english"])}</td>'
                f'<td>{escape(row["primary_disposition"])}<br>Model: {escape(row["model_review_status"])}</td>'
                f'<td>{unknowns}<br>Reserved by: {reservation}'
                f'<details><summary>All evidence</summary><pre>{evidence}</pre></details></td></tr>'
            )
        learned = target["selected_at"]
        status = f"Taught at card {learned['teaching_position']}" if learned else "Not taught"
        sections.append(
            '<details class="target"><summary>'
            f'{escape(target["lemma"])} ({escape(target["reading"])}) — {escape(target["gloss"])}'
            f' · {status} · {target["candidate_count"]} candidates</summary>'
            f'<p>{escape(target["learning_unit_key"])}</p><p>{counts(target["primary_counts"])}</p>'
            '<table><thead><tr><th>Candidate</th><th>Sentence</th><th>Disposition</th>'
            '<th>Final-state context / evidence</th></tr></thead><tbody>'
            + "".join(candidate_rows) + '</tbody></table></details>'
        )
    notices = "".join(f"<li>{escape(text)}</li>" for text in report["interpretation"])
    summary = escape(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    policy = escape(json.dumps(report["policy"], ensure_ascii=False, indent=2))
    sources = escape(json.dumps(report.get("sources", {}), ensure_ascii=False, indent=2))
    html = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Curriculum candidate accounting</title><style>
body{font:16px system-ui;background:#202124;color:#eee;margin:2rem;line-height:1.5}
table{border-collapse:collapse;width:100%}td,th{padding:.7rem;border:1px solid #555;text-align:left;vertical-align:top}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}details.target{border:1px solid #666;padding:.8rem;margin:.7rem 0}
summary{cursor:pointer}input{font:inherit;padding:.5rem;width:min(90%,40rem)}.target[hidden]{display:none}
</style><h1>Curriculum candidate accounting</h1>'''
    html += f"<ul>{notices}</ul><h2>Counts</h2><pre>{summary}</pre>"
    html += f"<details><summary>Policy, category precedence and input files</summary><pre>{policy}\n{escape(str(report['primary_precedence']))}\n{sources}</pre></details>"
    html += '<h2>Learning meanings and their alternatives</h2><label>Filter by word, meaning or sentence <input id="filter" type="search"></label>'
    html += "".join(sections)
    html += '''<script>
const targets = [...document.querySelectorAll('.target')];
const searchText = targets.map(t => t.textContent.toLowerCase());
document.querySelector('#filter').addEventListener('input', e => {
  const q = e.target.value.toLowerCase().trim();
  targets.forEach((t, i) => { t.hidden = !searchText[i].includes(q); });
});
</script></html>'''
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
