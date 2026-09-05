from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


SCHEMA_VERSION = 1

CATEGORY_FIELDS = {
    "reading": ("reading",),
    "sense": ("sense_key",),
    "gloss": ("gloss", "part_of_speech"),
    "sentence": (
        "sentence_id", "japanese", "target_surface", "target_start",
        "target_end", "target_lexical_spans",
    ),
    "translation": ("english",),
    "audio": (
        "season", "episode", "cue_index", "start_ms", "end_ms",
        "audio", "audio_path", "audio_filename",
    ),
    "unknown_count": (
        "unknown_context_words", "unknown_context_learning_unit_keys",
    ),
}

FINDING_RELEVANT_CATEGORIES = {
    "near_duplicate_learning_unit": {"sense", "gloss"},
    "audio_quality": {"audio", "sentence"},
    "overlapping_speech": {"audio", "sentence"},
    "subtitle_contamination": {"translation", "sentence"},
    "translation_quality": {"translation", "sentence"},
    "unknown_context_under_count": {"unknown_count", "sentence"},
    "compound_segmentation": {"unknown_count", "sentence"},
    "wrong_contextual_sense": {"sense", "gloss", "sentence"},
    "semantic_duplicate": {"sense", "gloss", "sentence"},
}

_KATAKANA = re.compile(r"[\u30a0-\u30ff]")
_JAPANESE_LETTER = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def load_card_artifact(path: Path) -> list[dict[str, Any]]:
    """Load either a plain card array or a curriculum selection artifact."""
    document = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if isinstance(document, list):
        cards = document
    elif isinstance(document, dict) and isinstance(document.get("accepted"), list):
        cards = document["accepted"]
    elif isinstance(document, dict) and isinstance(document.get("cards"), list):
        cards = document["cards"]
    else:
        raise ValueError(
            f"{path} must contain a card array or an object with a cards/accepted array"
        )
    if not all(isinstance(card, dict) for card in cards):
        raise ValueError(f"{path} contains a non-object card")
    return [dict(card) for card in cards]


def _identity(card: Mapping[str, Any]) -> str:
    key = str(card.get("learning_unit_key") or "").strip()
    if key:
        return key
    lexeme = str(card.get("lexeme_key") or "").strip()
    sense = str(card.get("sense_key") or "").strip()
    if lexeme and sense:
        return f"{lexeme}::{sense}"
    raise ValueError("Every compared card needs learning_unit_key or lexeme_key + sense_key")


def _indexed(cards: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], dict[str, int]]:
    by_key: dict[str, Mapping[str, Any]] = {}
    positions: dict[str, int] = {}
    for position, card in enumerate(cards, start=1):
        key = _identity(card)
        if key in by_key:
            raise ValueError(f"Duplicate learning unit in card artifact: {key}")
        by_key[key] = card
        positions[key] = position
    return by_key, positions


def _field_changes(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    categories: list[str] = []
    fields: dict[str, dict[str, Any]] = {}
    for category, names in CATEGORY_FIELDS.items():
        changed = False
        for name in names:
            before = baseline.get(name)
            after = candidate.get(name)
            if before != after:
                changed = True
                fields[name] = {"baseline": before, "candidate": after}
        if changed:
            categories.append(category)
    return categories, fields


def _replacement_pairs(
    removed_keys: Sequence[str],
    added_keys: Sequence[str],
    baseline_by_key: Mapping[str, Mapping[str, Any]],
    candidate_by_key: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str]]:
    """Pair unambiguous same-lexeme remove/add events as sense replacements."""
    removed_by_lexeme: dict[str, list[str]] = {}
    added_by_lexeme: dict[str, list[str]] = {}
    for key in removed_keys:
        removed_by_lexeme.setdefault(
            str(baseline_by_key[key].get("lexeme_key") or ""), []
        ).append(key)
    for key in added_keys:
        added_by_lexeme.setdefault(
            str(candidate_by_key[key].get("lexeme_key") or ""), []
        ).append(key)
    return [
        (removed[0], added_by_lexeme[lexeme][0])
        for lexeme, removed in removed_by_lexeme.items()
        if lexeme and len(removed) == 1 and len(added_by_lexeme.get(lexeme, [])) == 1
    ]


def _longest_common_subsequence(left: Sequence[str], right: Sequence[str]) -> set[str]:
    """Return one stable LCS, used to avoid treating simple position shifts as reorderings."""
    rows = len(left) + 1
    columns = len(right) + 1
    lengths = [[0] * columns for _ in range(rows)]
    for i, left_key in enumerate(left, start=1):
        for j, right_key in enumerate(right, start=1):
            if left_key == right_key:
                lengths[i][j] = lengths[i - 1][j - 1] + 1
            else:
                lengths[i][j] = max(lengths[i - 1][j], lengths[i][j - 1])
    result: set[str] = set()
    i, j = len(left), len(right)
    while i and j:
        if left[i - 1] == right[j - 1]:
            result.add(left[i - 1])
            i -= 1
            j -= 1
        elif lengths[i - 1][j] >= lengths[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return result


def _card_summary(card: Mapping[str, Any], position: int) -> dict[str, Any]:
    return {
        "position": position,
        "learning_unit_key": _identity(card),
        "lemma": card.get("lemma"),
        "reading": card.get("reading"),
        "gloss": card.get("gloss"),
        "japanese": card.get("japanese"),
        "english": card.get("english"),
    }


def _curriculum_checks(cards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    violations = []
    for position, card in enumerate(cards, start=1):
        limit = 0 if position <= 20 else 1 if position <= 200 else 2
        raw_count = card.get("unknown_context_words")
        if not isinstance(raw_count, int) or isinstance(raw_count, bool):
            violations.append({
                "position": position,
                "learning_unit_key": _identity(card),
                "actual": raw_count,
                "limit": limit,
                "reason": "missing_or_invalid_unknown_count",
            })
        elif raw_count > limit:
            violations.append({
                "position": position,
                "learning_unit_key": _identity(card),
                "actual": raw_count,
                "limit": limit,
                "reason": "unknown_count_exceeds_limit",
            })
    return {
        "passed": not violations,
        "policy": {
            "positions_1_through_20": 0,
            "positions_21_through_200": 1,
            "positions_after_200": 2,
        },
        "violations": violations,
    }


def _deck_quality_checks(cards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sentence_positions: dict[str, list[int]] = {}
    episode_counts: dict[str, int] = {}
    katakana_targets = 0
    lemmas = set()
    for position, card in enumerate(cards, start=1):
        sentence_identity = str(
            card.get("sentence_id")
            or f"{card.get('series')}:{card.get('season')}:{card.get('episode')}:{card.get('cue_index')}"
        )
        sentence_positions.setdefault(sentence_identity, []).append(position)
        episode = str(card.get("episode") or "unknown")
        episode_counts[episode] = episode_counts.get(episode, 0) + 1
        lemma = str(card.get("lemma") or "")
        if lemma:
            lemmas.add(lemma)
        letters = _JAPANESE_LETTER.findall(lemma)
        if letters and all(_KATAKANA.fullmatch(value) for value in letters):
            katakana_targets += 1
    duplicates = [
        {"sentence_identity": identity, "positions": positions}
        for identity, positions in sentence_positions.items()
        if len(positions) > 1
    ]
    count = len(cards)
    return {
        "unique_sentences": not duplicates,
        "duplicate_sentences": duplicates,
        "unique_lemmas": len(lemmas),
        "lemma_diversity": round(len(lemmas) / count, 6) if count else 0.0,
        "katakana_targets": katakana_targets,
        "katakana_ratio": round(katakana_targets / count, 6) if count else 0.0,
        "episode_counts": dict(sorted(episode_counts.items(), key=lambda item: item[0])),
    }


def _human_finding_checks(
    review: Optional[Mapping[str, Any]],
    baseline_cards: Sequence[Mapping[str, Any]],
    candidate_by_key: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not review:
        return []
    results = []
    for finding in review.get("flagged_cards", []):
        position = int(finding["position"])
        baseline_card = baseline_cards[position - 1]
        key = _identity(baseline_card)
        candidate = candidate_by_key.get(key)
        relevant = sorted({
            category
            for label in finding.get("categories", [])
            for category in FINDING_RELEVANT_CATEGORIES.get(label, set())
        })
        if candidate is None:
            status = "removed"
            changed_categories: list[str] = []
        else:
            changed_categories, _ = _field_changes(baseline_card, candidate)
            status = (
                "changed" if set(changed_categories).intersection(relevant)
                else "unchanged"
            )
        results.append({
            "baseline_position": position,
            "learning_unit_key": key,
            "categories": finding.get("categories", []),
            "status": status,
            "potentially_fixed": status in {"removed", "changed"},
            "manual_confirmation_required": status == "changed",
            "relevant_change_categories": relevant,
            "observed_change_categories": changed_categories,
            "user_note": finding.get("user_note"),
        })
    return results


def compare_card_sets(
    baseline_cards: Sequence[Mapping[str, Any]],
    candidate_cards: Sequence[Mapping[str, Any]],
    *,
    human_review: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    baseline_by_key, baseline_positions = _indexed(baseline_cards)
    candidate_by_key, candidate_positions = _indexed(candidate_cards)
    baseline_keys = list(baseline_by_key)
    candidate_keys = list(candidate_by_key)
    retained_keys = [key for key in baseline_keys if key in candidate_by_key]
    removed_keys = [key for key in baseline_keys if key not in candidate_by_key]
    added_keys = [key for key in candidate_keys if key not in baseline_by_key]

    common_baseline = [key for key in baseline_keys if key in candidate_by_key]
    common_candidate = [key for key in candidate_keys if key in baseline_by_key]
    stable_order = _longest_common_subsequence(common_baseline, common_candidate)
    reordered_keys = [key for key in common_candidate if key not in stable_order]

    changed = []
    category_counts = {category: 0 for category in CATEGORY_FIELDS}
    for key in retained_keys:
        categories, fields = _field_changes(
            baseline_by_key[key], candidate_by_key[key]
        )
        if not categories:
            continue
        for category in categories:
            category_counts[category] += 1
        changed.append({
            "match": "learning_unit",
            "learning_unit_key": key,
            "baseline_position": baseline_positions[key],
            "candidate_position": candidate_positions[key],
            "lemma": candidate_by_key[key].get("lemma"),
            "categories": categories,
            "fields": fields,
        })

    replacements = []
    for baseline_key, candidate_key in _replacement_pairs(
        removed_keys, added_keys, baseline_by_key, candidate_by_key
    ):
        categories, fields = _field_changes(
            baseline_by_key[baseline_key], candidate_by_key[candidate_key]
        )
        if "sense" not in categories:
            categories.insert(0, "sense")
        for category in categories:
            category_counts[category] += 1
        replacement = {
            "match": "lexeme",
            "learning_unit_key": candidate_key,
            "baseline_learning_unit_key": baseline_key,
            "baseline_position": baseline_positions[baseline_key],
            "candidate_position": candidate_positions[candidate_key],
            "lemma": candidate_by_key[candidate_key].get("lemma"),
            "categories": categories,
            "fields": fields,
        }
        replacements.append(replacement)
        changed.append(replacement)

    report = {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "baseline_cards": len(baseline_cards),
            "candidate_cards": len(candidate_cards),
            "retained": len(retained_keys),
            "removed": len(removed_keys),
            "added": len(added_keys),
            "reordered": len(reordered_keys),
            "learner_visible_changed": len(changed),
            "sense_replacements": len(replacements),
            "change_categories": category_counts,
        },
        "retained": [
            {
                "learning_unit_key": key,
                "baseline_position": baseline_positions[key],
                "candidate_position": candidate_positions[key],
            }
            for key in retained_keys
        ],
        "removed": [
            _card_summary(baseline_by_key[key], baseline_positions[key])
            for key in removed_keys
        ],
        "added": [
            _card_summary(candidate_by_key[key], candidate_positions[key])
            for key in added_keys
        ],
        "reordered": [
            {
                "learning_unit_key": key,
                "lemma": candidate_by_key[key].get("lemma"),
                "baseline_position": baseline_positions[key],
                "candidate_position": candidate_positions[key],
            }
            for key in reordered_keys
        ],
        "replacements": replacements,
        "changed": changed,
        "checks": {
            "curriculum_unknown_words": _curriculum_checks(candidate_cards),
            "deck_quality": _deck_quality_checks(candidate_cards),
            "human_findings": _human_finding_checks(
                human_review, baseline_cards, candidate_by_key
            ),
        },
    }
    return report


def _render_card_rows(items: Sequence[Mapping[str, Any]], empty: str) -> str:
    if not items:
        return f'<p class="empty">{html.escape(empty)}</p>'
    rows = []
    for item in items:
        position = item.get("position", item.get("candidate_position", ""))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(position))}</td>"
            f"<td>{html.escape(str(item.get('lemma') or ''))}</td>"
            f"<td>{html.escape(str(item.get('reading') or ''))}</td>"
            f"<td>{html.escape(str(item.get('gloss') or ''))}</td>"
            f"<td>{html.escape(str(item.get('japanese') or ''))}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>#</th><th>Word</th><th>Reading</th><th>Gloss</th><th>Sentence</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def render_comparison_html(report: Mapping[str, Any], output: Path) -> Path:
    summary = report["summary"]
    curriculum = report["checks"]["curriculum_unknown_words"]
    quality = report["checks"]["deck_quality"]
    finding_rows = []
    for item in report["checks"]["human_findings"]:
        finding_rows.append(
            "<tr>"
            f"<td>{item['baseline_position']}</td>"
            f"<td>{html.escape(', '.join(item['categories']))}</td>"
            f"<td class=\"{html.escape(item['status'])}\">{html.escape(item['status'])}</td>"
            f"<td>{html.escape(str(item.get('user_note') or ''))}</td>"
            "</tr>"
        )
    changed_rows = []
    for item in report["changed"]:
        changed_rows.append(
            "<tr>"
            f"<td>{item['baseline_position']} → {item['candidate_position']}</td>"
            f"<td>{html.escape(str(item.get('lemma') or ''))}</td>"
            f"<td>{html.escape(', '.join(item['categories']))}</td>"
            f"<td><code>{html.escape(', '.join(item['fields']))}</code></td>"
            "</tr>"
        )
    reordered_rows = []
    for item in report["reordered"]:
        reordered_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('lemma') or ''))}</td>"
            f"<td>{item['baseline_position']}</td>"
            f"<td>{item['candidate_position']}</td>"
            "</tr>"
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vocabulary baseline comparison</title><style>
:root {{ color-scheme: dark; font-family: system-ui,sans-serif; }} body {{ max-width:1200px;margin:0 auto;padding:32px;background:#202124;color:#f2f2f2; }}
h1,h2 {{ margin-top:1.5em; }} .metrics {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:12px; }} .metric {{ background:#2b2c2f;border:1px solid #484a4f;border-radius:10px;padding:14px; }} .metric strong {{ display:block;font-size:1.8rem; }}
table {{ width:100%;border-collapse:collapse;background:#292a2d; }} th,td {{ padding:10px;border-bottom:1px solid #494b50;text-align:left;vertical-align:top; }} th {{ color:#b9adff; }} code {{ color:#d4caff; }} .passed,.removed {{ color:#8bdd98; }} .changed {{ color:#ffd27d; }} .unchanged,.failed {{ color:#ff8f8f; }} .empty {{ color:#aeb2ba; }}
</style></head><body><h1>Vocabulary baseline comparison</h1>
<div class="metrics">{''.join(f'<div class="metric"><strong>{summary[name]}</strong>{name.replace("_", " ")}</div>' for name in ("baseline_cards", "candidate_cards", "retained", "removed", "added", "reordered", "learner_visible_changed"))}</div>
<h2>Curriculum gate</h2><p class="{'passed' if curriculum['passed'] else 'failed'}">{'Passed' if curriculum['passed'] else 'Failed'} — {len(curriculum['violations'])} violation(s).</p>
<h2>Deck quality</h2><p>{quality['unique_lemmas']} unique lemmas · {quality['katakana_targets']} katakana targets ({quality['katakana_ratio']:.1%}) · {len(quality['duplicate_sentences'])} duplicate sentence(s)</p>
<h2>Frozen human findings</h2><table><thead><tr><th>Baseline #</th><th>Finding</th><th>Status</th><th>Review note</th></tr></thead><tbody>{''.join(finding_rows) or '<tr><td colspan="4">No human findings supplied.</td></tr>'}</tbody></table>
<h2>Learner-visible changes</h2><table><thead><tr><th>Position</th><th>Word</th><th>Categories</th><th>Fields</th></tr></thead><tbody>{''.join(changed_rows) or '<tr><td colspan="4">No learner-visible changes.</td></tr>'}</tbody></table>
<h2>Reordered cards</h2><table><thead><tr><th>Word</th><th>Baseline #</th><th>Candidate #</th></tr></thead><tbody>{''.join(reordered_rows) or '<tr><td colspan="3">No cards reordered.</td></tr>'}</tbody></table>
<h2>Removed cards</h2>{_render_card_rows(report['removed'], 'No cards removed.')}
<h2>Added cards</h2>{_render_card_rows(report['added'], 'No cards added.')}
</body></html>"""
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination


def write_comparison_json(report: Mapping[str, Any], output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
