from __future__ import annotations

import base64
import html
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .card_format import blank_target, highlight_target, hiragana, learner_pos
from .database import VocabularyDatabase
from .media import render_card_media


MODEL_NAME = "Multi-source Japanese Vocabulary"
FIELDS = [
    "LexemeKey", "Expression", "Reading", "PartOfSpeech", "Gloss", "Sentence",
    "SentenceCloze", "SentenceAnswer", "SentenceEnglish", "SentenceAudio", "Image",
    "Source", "Metadata",
]
FRONT = """<div class=prompt>{{Gloss}} <span class=pos>{{PartOfSpeech}}</span></div>
<div class="sentence cloze">{{SentenceCloze}}</div>
<div class=translation>{{SentenceEnglish}}</div>"""
BACK = """{{FrontSide}}<hr id=answer>
<div class=expression><ruby>{{Expression}}<rt>{{Reading}}</rt></ruby></div>
<div class="sentence full">{{SentenceAnswer}}</div>
<div class=media>{{SentenceAudio}}{{Image}}</div>
<div class=source>{{Source}}</div>"""
CSS = """.card { font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif;
text-align:center; color:#f7f7f7; background:#292929; font-size:22px; padding:30px 18px; }
.prompt { font-size:42px; margin:15px 5px 50px; } .pos { color:#625cff; font-size:.55em; }
.sentence { font:46px/1.65 "Yu Mincho", "Hiragino Mincho ProN", serif; margin:28px 8px; }
.target-blank { display:inline-block; min-width:2.5em; white-space:nowrap; }
.translation { font-size:27px; font-weight:650; margin:50px 8px; }
#answer { border:0; border-top:2px solid #737373; margin:42px -18px; }
.expression { font-size:46px; margin:24px; } ruby rt { font-size:.42em; }
.target-answer { font-weight:800; } .source { color:#aaa; font-size:13px; margin-top:20px; }
.media img { display:block; max-width:90%; max-height:360px; border-radius:8px; margin:20px auto; }
.media audio { display:block; width:min(520px,90%); margin:30px auto 16px; }
.nightMode .card { color:#f7f7f7; background:#292929; }"""


class AnkiConnectError(RuntimeError):
    pass


class AnkiConnect:
    def __init__(self, url: str = "http://127.0.0.1:8765"):
        self.url = url

    def invoke(self, action: str, **params: Any) -> Any:
        payload = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AnkiConnectError(
                "Cannot reach AnkiConnect. Open Anki and install/enable the AnkiConnect add-on."
            ) from exc
        if result.get("error"):
            raise AnkiConnectError(str(result["error"]))
        return result.get("result")

    def ensure_model(self) -> None:
        if MODEL_NAME in self.invoke("modelNames"):
            existing_fields = set(self.invoke("modelFieldNames", modelName=MODEL_NAME))
            for field in FIELDS:
                if field not in existing_fields:
                    self.invoke("modelFieldAdd", modelName=MODEL_NAME, fieldName=field)
            self.invoke(
                "updateModelTemplates",
                model={
                    "name": MODEL_NAME,
                    "templates": {"Recognition": {"Front": FRONT, "Back": BACK}},
                },
            )
            self.invoke("updateModelStyling", model={"name": MODEL_NAME, "css": CSS})
            return
        self.invoke(
            "createModel",
            modelName=MODEL_NAME,
            inOrderFields=FIELDS,
            css=CSS,
            cardTemplates=[{"Name": "Recognition", "Front": FRONT, "Back": BACK}],
            isCloze=False,
        )

    def ensure_deck(self, deck: str) -> None:
        self.invoke("createDeck", deck=deck)

    def store_media(self, path: Path) -> str:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return str(self.invoke("storeMediaFile", filename=path.name, data=data))


def _source_deck(row: Dict[str, Any]) -> str:
    safe_series = str(row["series"]).replace("::", "-")
    return f"Japanese Sources::{safe_series}"


def sync_source(
    database: VocabularyDatabase,
    source_ids: Sequence[int],
    *,
    limit: int = 20,
    metric: str = "hybrid",
    media_directory: Path = Path(".vocabdeck/media"),
    client: Optional[AnkiConnect] = None,
) -> Dict[str, int]:
    client = client or AnkiConnect()
    learned = 0
    tracked = database.tracked_anki_cards()
    if tracked:
        info = client.invoke("cardsInfo", cards=[int(row["card_id"]) for row in tracked])
        by_card = {int(item["cardId"]): item for item in info}
        for row in tracked:
            card = by_card.get(int(row["card_id"]))
            if card is None:
                continue
            reps = int(card.get("reps", 0))
            if reps > 0 and int(row["last_seen_reps"]) == 0:
                learned += 1
            database.update_anki_reps(int(row["lexeme_id"]), reps)

    client.ensure_model()
    rows = database.next_unseen_for_sources(source_ids, limit, metric)
    added = 0
    moved = 0
    for row in rows:
        deck = _source_deck(row)
        client.ensure_deck(deck)
        sentence_audio = ""
        image = ""
        video_path = row.get("video_path")
        if video_path and Path(video_path).exists():
            files = render_card_media(
                Path(video_path), int(row["start_ms"]), int(row["end_ms"]),
                media_directory, str(row["lexeme_key"]),
            )
            audio_name = client.store_media(files["audio"])
            image_name = client.store_media(files["image"])
            sentence_audio = f"[sound:{audio_name}]"
            image = f'<img src="{html.escape(image_name, quote=True)}">'
        source_label = f"{row['series']} S{int(row['season']):02d}E{int(row['episode']):02d}"
        metadata = json.dumps(
            {
                "series": row["series"], "season": row["season"], "episode": row["episode"],
                "start_ms": row["start_ms"], "end_ms": row["end_ms"],
                "difficulty_metric": row["difficulty_metric"],
                "difficulty_score": row["difficulty_score"],
                "difficulty_breakdown": row["difficulty_breakdown"],
                "dictionary_entry_id": row.get("dictionary_entry_id"),
                "dictionary_sense_index": row.get("dictionary_sense_index"),
                "dictionary_confidence": row.get("dictionary_confidence"),
                "target_surface": row.get("target_surface"),
                "example_progression": row.get("example_progression"),
            },
            ensure_ascii=False,
        )
        target = str(row.get("target_surface") or row["lemma"])
        fields = {
            "LexemeKey": str(row["lexeme_key"]), "Expression": str(row["lemma"]),
            "Reading": hiragana(str(row["reading"])),
            "PartOfSpeech": learner_pos(str(row["part_of_speech"])),
            "Gloss": str(row.get("gloss") or ""), "Sentence": str(row["japanese"]),
            "SentenceCloze": blank_target(str(row["japanese"]), target),
            "SentenceAnswer": highlight_target(str(row["japanese"]), target),
            "SentenceEnglish": str(row.get("english") or ""), "SentenceAudio": sentence_audio,
            "Image": image, "Source": source_label, "Metadata": metadata,
        }
        if row.get("note_id") is not None:
            note_id = int(row["note_id"])
            card_id = int(row["card_id"])
            client.invoke("updateNoteFields", note={"id": note_id, "fields": fields})
            client.invoke("changeDeck", cards=[card_id], deck=deck)
            database.record_anki_card(
                int(row["lexeme_id"]), note_id, card_id, int(row["source_id"])
            )
            moved += 1
            continue
        note_id = int(
            client.invoke(
                "addNote",
                note={
                    "deckName": deck,
                    "modelName": MODEL_NAME,
                    "fields": fields,
                    "options": {"allowDuplicate": False},
                    "tags": ["multisource_vocab", f"series::{row['series'].replace(' ', '_')}"],
                },
            )
        )
        cards = client.invoke("findCards", query=f"nid:{note_id}")
        database.record_anki_card(
            int(row["lexeme_id"]), note_id, int(cards[0]), int(row["source_id"])
        )
        added += 1
    return {
        "learned": learned,
        "added": added,
        "moved_unreviewed": moved,
        "batch_size": added + moved,
    }
