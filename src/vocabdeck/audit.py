from __future__ import annotations

import html
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .semantics import MultilingualE5Small, TextEmbedder


ALIGNMENT_WARNING_THRESHOLD = 0.78
ALIGNMENT_HIGH_THRESHOLD = 0.72
GLOSS_WARNING_THRESHOLD = 0.70
EXPRESSION_MARGIN_WARNING = 0.06
EXPRESSION_OPACITY_WARNING = 0.20


@dataclass(frozen=True)
class AuditFinding:
    code: str
    severity: str
    title: str
    explanation: str
    score: Optional[float] = None
    threshold: Optional[float] = None


def _finding(
    code: str,
    severity: str,
    title: str,
    explanation: str,
    score: Optional[float] = None,
    threshold: Optional[float] = None,
) -> AuditFinding:
    return AuditFinding(
        code=code,
        severity=severity,
        title=title,
        explanation=explanation,
        score=None if score is None else round(float(score), 3),
        threshold=threshold,
    )


def audit_queue(
    database: Any,
    source_ids: Sequence[int],
    limit: int = 100,
    metric: str = "hybrid",
    embedder: Optional[TextEmbedder] = None,
) -> Dict[str, Any]:
    """Audit the exact progressive batch that would next be sent to Anki."""
    rows = database.next_unseen_for_sources(source_ids, limit, metric)
    semantic = embedder or MultilingualE5Small()
    cards: List[Dict[str, Any]] = []
    severity_counts = {"high": 0, "medium": 0, "info": 0}
    code_counts: Dict[str, int] = {}

    for position, raw_row in enumerate(rows, start=1):
        row = dict(raw_row)
        findings: List[AuditFinding] = []
        japanese = str(row.get("japanese") or "")
        english = str(row.get("english") or "").strip()
        gloss = str(row.get("gloss") or "").strip()

        alignment_score: Optional[float] = None
        if not english:
            findings.append(_finding(
                "missing_translation", "high", "English translation is missing",
                "This example cannot support translation or dictionary-sense checks.",
            ))
        else:
            alignment_score = semantic.similarity(japanese, english)
            if alignment_score < ALIGNMENT_WARNING_THRESHOLD:
                severity = (
                    "high" if alignment_score < ALIGNMENT_HIGH_THRESHOLD else "medium"
                )
                findings.append(_finding(
                    "weak_subtitle_alignment", severity, "Translation deserves review",
                    "The Japanese and English have weak semantic similarity. This can indicate an idiomatic translation or a subtitle alignment error.",
                    alignment_score, ALIGNMENT_WARNING_THRESHOLD,
                ))

        gloss_score: Optional[float] = None
        if not gloss:
            findings.append(_finding(
                "missing_definition", "high", "Dictionary definition is missing",
                "No learner-facing JMdict gloss was selected for this word.",
            ))
        elif english:
            gloss_score = semantic.similarity(
                english, f"The target Japanese word means: {gloss}"
            )
            if gloss_score < GLOSS_WARNING_THRESHOLD:
                findings.append(_finding(
                    "weak_gloss_support", "medium", "Definition has weak context support",
                    "The selected definition is not strongly supported by this example's English subtitle. It may be a different sense.",
                    gloss_score, GLOSS_WARNING_THRESHOLD,
                ))

        progression = row.get("example_progression") or {}
        harder_count = int(progression.get("harder_unknown_words", 0))
        if harder_count:
            harder_ids = progression.get("harder_unknown_ids") or []
            harder_words = database.lexeme_labels(harder_ids)
            suffix = f": {', '.join(harder_words)}" if harder_words else ""
            findings.append(_finding(
                "harder_unknown_context", "high", "Example contains harder unknown vocabulary",
                f"{harder_count} unknown context word(s) are harder than the target{suffix}.",
            ))

        variants = database.reading_variants(str(row["lemma"]), str(row["reading"]))
        if variants:
            findings.append(_finding(
                "alternate_reading", "info", "Same spelling has another recorded reading",
                "Other global identities: " + ", ".join(variants) +
                ". Confirm that this occurrence uses the displayed reading.",
            ))

        analyses = database.expression_analyses_for_sentence(row.get("sentence_id"))
        target_start = row.get("target_start")
        target_end = row.get("target_end")
        relevant_analyses = []
        for analysis in analyses:
            overlaps_target = (
                target_start is None or target_end is None
                or (int(analysis["start_char"]) < int(target_end)
                    and int(analysis["end_char"]) > int(target_start))
            )
            if not overlaps_target:
                continue
            relevant_analyses.append(dict(analysis))
            decision = str(analysis["decision"])
            margin = float(analysis["margin"])
            opacity = float(analysis["opacity"])
            surface = str(analysis["surface"])
            if decision in {"ambiguous", "insufficient_evidence"}:
                findings.append(_finding(
                    "ambiguous_expression", "medium", "Expression interpretation is uncertain",
                    f"“{surface}” was kept as component words because the phrase interpretation lacked decisive evidence.",
                    margin, EXPRESSION_MARGIN_WARNING,
                ))
            elif decision == "expression" and (
                margin < EXPRESSION_MARGIN_WARNING
                or opacity < EXPRESSION_OPACITY_WARNING
            ):
                weak_margin = margin < EXPRESSION_MARGIN_WARNING
                findings.append(_finding(
                    "borderline_expression", "medium", "Expression decision is borderline",
                    f"“{surface}” was accepted as one expression, but its semantic margin or opacity is close to the decision boundary.",
                    margin if weak_margin else opacity,
                    EXPRESSION_MARGIN_WARNING if weak_margin else EXPRESSION_OPACITY_WARNING,
                ))

        for finding in findings:
            severity_counts[finding.severity] += 1
            code_counts[finding.code] = code_counts.get(finding.code, 0) + 1
        row["audit_position"] = position
        row["alignment_score"] = None if alignment_score is None else round(alignment_score, 3)
        row["gloss_score"] = None if gloss_score is None else round(gloss_score, 3)
        row["audit_findings"] = [asdict(finding) for finding in findings]
        row["expression_analyses"] = relevant_analyses
        cards.append(row)

    excluded = (
        database.excluded_candidates(source_ids, limit)
        if hasattr(database, "excluded_candidates") else []
    )

    return {
        "summary": {
            "cards": len(cards),
            "cards_with_findings": sum(bool(card["audit_findings"]) for card in cards),
            "excluded_candidates": len(excluded),
            "findings": sum(severity_counts.values()),
            "severity_counts": severity_counts,
            "code_counts": dict(sorted(code_counts.items())),
            "metric": metric,
        },
        "cards": cards,
        "excluded": excluded,
    }


def render_audit_html(report: Mapping[str, Any], output: Path) -> Path:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    cards_html = []
    for card in report["cards"]:
        findings = card["audit_findings"]
        severities = " ".join(sorted({item["severity"] for item in findings})) or "passed"
        finding_html = "".join(
            f"""<li class="finding {html.escape(item['severity'])}">
  <strong>{html.escape(item['title'])}</strong>
  <span>{html.escape(item['explanation'])}</span>
  {f'<code>{float(item["score"]):.3f} / {float(item["threshold"]):.3f}</code>' if item['score'] is not None and item['threshold'] is not None else ''}
</li>"""
            for item in findings
        ) or '<li class="finding passed"><strong>No automatic warnings</strong><span>This card passed the current audit rules.</span></li>'
        alignment = card.get("alignment_score")
        gloss_score = card.get("gloss_score")
        cards_html.append(f"""<article class="card" data-severity="{severities}">
  <header><span class="position">#{int(card['audit_position'])}</span>
    <h2><ruby>{html.escape(str(card['lemma']))}<rt>{html.escape(str(card['reading']))}</rt></ruby></h2>
    <span class="source">{html.escape(str(card['series']))} S{int(card['season']):02d}E{int(card['episode']):02d}</span>
  </header>
  <p class="gloss">{html.escape(str(card.get('gloss') or 'Definition unavailable'))}</p>
  <p class="japanese">{html.escape(str(card['japanese']))}</p>
  <p class="english">{html.escape(str(card.get('english') or 'No English subtitle'))}</p>
  <div class="scores"><span>Difficulty {float(card['difficulty_score']):.1f}</span>
    <span>Alignment {'—' if alignment is None else f'{float(alignment):.3f}'}</span>
    <span>Gloss support {'—' if gloss_score is None else f'{float(gloss_score):.3f}'}</span></div>
  <ul>{finding_html}</ul>
</article>""")

    severity = summary["severity_counts"]
    excluded_html = []
    exclusion_titles = {
        "reaction_fragment": "Reaction fragment",
        "missing_definition": "No reliable definition",
    }
    for item in report.get("excluded", []):
        reason = str(item["exclusion_reason"])
        excluded_html.append(f"""<article class="card excluded" data-severity="excluded">
  <header><span class="position">Excluded</span>
    <h2><ruby>{html.escape(str(item['lemma']))}<rt>{html.escape(str(item['reading']))}</rt></ruby></h2>
    <span class="source">{html.escape(str(item['series']))} S{int(item['season']):02d}E{int(item['episode']):02d}</span>
  </header>
  <p class="gloss">{html.escape(exclusion_titles.get(reason, reason))}</p>
  <p class="japanese">{html.escape(str(item['japanese']))}</p>
  <p class="english">{html.escape(str(item.get('english') or 'No English subtitle'))}</p>
  <ul><li class="finding high"><strong>Not eligible for Anki</strong>
    <span>{'The tokenizer found a one-kana reaction or sound fragment.' if reason == 'reaction_fragment' else 'No POS-compatible learner definition was found.'}</span></li></ul>
</article>""")
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vocabulary quality audit</title><style>
:root {{ color-scheme:dark; font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:#202124; color:#f1f3f4; }}
main {{ width:min(1100px,100%); margin:auto; padding:36px 24px 80px; }}
h1 {{ margin:0 0 8px; }} .summary {{ color:#bdc1c6; margin-bottom:24px; }}
.filters {{ display:flex; gap:8px; flex-wrap:wrap; position:sticky; top:0; z-index:2; padding:12px 0; background:#202124ee; }}
button {{ border:1px solid #5f6368; border-radius:999px; background:#303134; color:#f1f3f4; padding:8px 14px; cursor:pointer; }}
button.active {{ background:#4f46e5; border-color:#7770ff; }}
.card {{ background:#292a2d; border:1px solid #45464a; border-radius:12px; padding:22px; margin:14px 0; }}
header {{ display:flex; align-items:baseline; gap:14px; }} h2 {{ font-size:34px; margin:0; }} ruby rt {{ font-size:.38em; }}
.position,.source,.scores {{ color:#9aa0a6; }} .source {{ margin-left:auto; }}
.gloss {{ color:#c9c5ff; font-size:18px; }} .japanese {{ font-family:"Yu Mincho",serif; font-size:28px; margin-bottom:6px; }}
.english {{ font-size:18px; margin-top:0; }} .scores {{ display:flex; gap:18px; flex-wrap:wrap; font-size:13px; }}
ul {{ list-style:none; padding:0; margin:18px 0 0; }} .finding {{ display:grid; grid-template-columns:minmax(190px,.7fr) 2fr auto; gap:12px; border-top:1px solid #45464a; padding:12px 0; }}
.finding.high strong {{ color:#ff8a80; }} .finding.medium strong {{ color:#ffd180; }} .finding.info strong {{ color:#82b1ff; }} .finding.passed strong {{ color:#8fd694; }}
code {{ color:#bdc1c6; }} @media(max-width:700px) {{ .finding {{ grid-template-columns:1fr; }} .source {{ margin-left:0; }} header {{ flex-wrap:wrap; }} }}
</style></head><body><main><h1>Vocabulary quality audit</h1>
<p class="summary">{int(summary['cards'])} cards · {int(summary['cards_with_findings'])} flagged ·
{int(severity['high'])} high · {int(severity['medium'])} medium · {int(severity['info'])} informational ·
{int(summary.get('excluded_candidates', 0))} excluded</p>
<nav class="filters"><button class="active" data-filter="all">All</button><button data-filter="flagged">Flagged</button>
<button data-filter="high">High</button><button data-filter="medium">Medium</button><button data-filter="passed">Passed</button>
<button data-filter="excluded">Excluded</button></nav>
<h2 class="section-title">Eligible queue</h2>{''.join(cards_html)}
<h2 class="section-title">Excluded candidates</h2>{''.join(excluded_html) or '<p class="summary">No candidates were excluded.</p>'}</main><script>
const buttons=[...document.querySelectorAll('button[data-filter]')]; const cards=[...document.querySelectorAll('.card')];
buttons.forEach(button=>button.addEventListener('click',()=>{{ buttons.forEach(item=>item.classList.remove('active')); button.classList.add('active'); const value=button.dataset.filter; cards.forEach(card=>{{ const tags=card.dataset.severity.split(' '); card.hidden=!(value==='all'||(value==='flagged'&&!tags.includes('passed'))||tags.includes(value)); }}); }}));
</script></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output
