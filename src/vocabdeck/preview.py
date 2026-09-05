from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Mapping, Sequence

from .card_format import (
    blank_target, highlight_target, hiragana, learner_pos, learner_target_span,
    learner_target_spans,
)
from .media import render_card_media


def render_preview_html(
    rows: Sequence[Mapping[str, Any]], output: Path, include_media: bool = True
) -> Path:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    assets = output.parent / f"{output.stem}_assets"
    cards = []
    for index, row in enumerate(rows):
        media_html = ""
        video = Path(str(row.get("video_path") or ""))
        if include_media and video.is_file():
            files = render_card_media(
                video, int(row["start_ms"]), int(row["end_ms"]), assets,
                str(row["lexeme_key"]),
            )
            image_src = html.escape(files["image"].relative_to(output.parent).as_posix())
            audio_src = html.escape(files["audio"].relative_to(output.parent).as_posix())
            media_html = f"""
      <audio controls preload="none" src="{audio_src}"></audio>
      <img loading="lazy" src="{image_src}" alt="Source frame">"""
        progression = row.get("example_progression") or {}
        scheduling = row.get("scheduling") or {}
        content_words = int(progression.get("content_words", row.get("sentence_word_count", 0)))
        unknown_words = int(scheduling.get(
            "unknown_context_words",
            row.get("unknown_context_words", progression.get("unknown_other_words", 0)),
        ))
        unknown_label = "word" if unknown_words == 1 else "words"
        target, target_start, target_end = learner_target_span(row)
        target_spans = learner_target_spans(row)
        cloze = blank_target(
            str(row["japanese"]), target, target_start, target_end, target_spans
        )
        answer_sentence = highlight_target(
            str(row["japanese"]), target, target_start, target_end, target_spans
        )
        hidden = "" if index == 0 else " hidden"
        cards.append(
            f"""<article class="review-card" data-card="{index}"{hidden}>
  <section class="front">
    <div class="prompt"><span class="gloss">{html.escape(str(row.get('gloss') or 'Definition unavailable'))}</span>
      <span class="pos">{html.escape(learner_pos(str(row.get('part_of_speech') or '')))}</span></div>
    <div class="sentence cloze">{cloze}</div>
    <div class="translation">{html.escape(str(row.get('english') or ''))}</div>
  </section>
  <section class="answer" hidden>
    <div class="divider"></div>
    <div class="expression"><ruby>{html.escape(str(row['lemma']))}<rt>{html.escape(hiragana(str(row['reading'])))}</rt></ruby></div>
    <div class="sentence full">{answer_sentence}</div>
    <div class="meta">{content_words} content words ·
      {unknown_words} other unknown {unknown_label} (excluding the target)</div>
    {media_html}
    <div class="meta">Word difficulty {float(row['difficulty_score']):.1f} ·
      {int(progression.get('harder_unknown_words', 0))} harder than target ·
      {html.escape(str(row['series']))} S{int(row['season']):02d}E{int(row['episode']):02d}
    </div>
  </section>
</article>"""
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Japanese vocabulary review preview</title>
<style>
:root {{ color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif; }}
* {{ box-sizing:border-box; }} [hidden] {{ display:none !important; }}
body {{ margin:0; min-height:100vh; background:#292929; color:#f7f7f7; }}
main {{ width:min(1100px, 100%); min-height:calc(100vh - 82px); margin:auto; padding:52px 28px 32px;
  display:flex; flex-direction:column; justify-content:center; }}
.review-card {{ text-align:center; width:100%; }}
.prompt {{ font-size:clamp(27px, 4vw, 54px); line-height:1.25; margin-bottom:58px; }}
.gloss {{ font-weight:450; }} .pos {{ color:#625cff; font-size:.52em; white-space:nowrap; }}
.sentence {{ font-size:clamp(35px, 5vw, 66px); line-height:1.65; font-family:"Yu Mincho", "Hiragino Mincho ProN", serif; }}
.target-blank {{ display:inline-block; min-width:2.5em; white-space:nowrap; }}
.translation {{ font-size:clamp(20px, 2.3vw, 32px); font-weight:650; margin:62px 0 44px; }}
.divider {{ height:2px; background:#737373; margin:0 calc(50% - 50vw) 52px; }}
.expression {{ font-size:clamp(38px, 5vw, 62px); margin:0 0 38px; }}
ruby rt {{ font-size:.42em; font-weight:400; }}
.full {{ font-size:clamp(29px, 4vw, 52px); }}
.target-answer {{ font-weight:800; }}
audio {{ display:block; width:min(520px, 90%); margin:42px auto 22px; }}
img {{ display:block; width:min(720px, 90%); max-height:405px; object-fit:contain; margin:22px auto;
  border-radius:8px; background:#111; }}
.meta {{ color:#b8b8b8; font-size:14px; margin-top:28px; }}
.controls {{ position:sticky; bottom:0; display:flex; align-items:center; justify-content:center; gap:12px;
  height:82px; padding:14px; background:#202020ee; border-top:1px solid #444; }}
button {{ border:1px solid #666; border-radius:8px; padding:12px 22px; background:#383838; color:white;
  font:600 16px inherit; cursor:pointer; }} button.primary {{ min-width:190px; background:#4f46e5; border-color:#7069ff; }}
button:disabled {{ opacity:.35; cursor:default; }} #progress {{ min-width:76px; text-align:center; color:#ccc; }}
</style></head><body>
<main>{''.join(cards)}</main>
<nav class="controls" aria-label="Preview controls">
  <button id="previous" type="button">Previous</button>
  <span id="progress"></span>
  <button id="show" class="primary" type="button">Show answer</button>
  <button id="next" type="button">Next</button>
</nav>
<script>
const cards = [...document.querySelectorAll('.review-card')];
let current = 0;
function render() {{
  cards.forEach((card, index) => card.hidden = index !== current);
  const answer = cards[current]?.querySelector('.answer');
  if (answer) answer.hidden = true;
  document.querySelector('#progress').textContent = `${{current + 1}} / ${{cards.length}}`;
  document.querySelector('#previous').disabled = current === 0;
  document.querySelector('#next').disabled = current >= cards.length - 1;
  document.querySelector('#show').textContent = 'Show answer';
  window.scrollTo(0, 0);
}}
document.querySelector('#show').addEventListener('click', () => {{
  const answer = cards[current].querySelector('.answer');
  answer.hidden = !answer.hidden;
  document.querySelector('#show').textContent = answer.hidden ? 'Show answer' : 'Hide answer';
}});
document.querySelector('#previous').addEventListener('click', () => {{ if (current > 0) {{ current--; render(); }} }});
document.querySelector('#next').addEventListener('click', () => {{ if (current < cards.length - 1) {{ current++; render(); }} }});
document.addEventListener('keydown', event => {{
  if (event.code === 'Space') {{ event.preventDefault(); document.querySelector('#show').click(); }}
  if (event.code === 'ArrowRight') document.querySelector('#next').click();
  if (event.code === 'ArrowLeft') document.querySelector('#previous').click();
}});
render();
</script></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output
