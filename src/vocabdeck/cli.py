from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, Sequence

from .database import VocabularyDatabase
from .anki import sync_source
from .difficulty import METRICS
from .media import extract_subtitle_stream, probe_subtitle_streams
from .preview import render_preview_html
from .subtitles import merge_continuations, read_srt
from .tokenizer import JapaneseTokenizer


def _semantic_tokenizer() -> JapaneseTokenizer:
    from .semantics import ExpressionSemanticScorer

    return JapaneseTokenizer(expression_scorer=ExpressionSemanticScorer())


def _database(path: str) -> VocabularyDatabase:
    db = VocabularyDatabase(Path(path).expanduser().resolve())
    db.initialize()
    return db


def _episode_selection(value: str) -> list:
    selected = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if end < start:
                raise argparse.ArgumentTypeError("episode range end must not precede start")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(part))
    if not selected:
        raise argparse.ArgumentTypeError("select at least one episode")
    return sorted(selected)


def _source_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--series", required=True)
    parser.add_argument("--season", required=True, type=int)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--episode", type=int)
    choice.add_argument("--episodes", type=_episode_selection, help="range such as 1-10,12")


def _selected_source_ids(db: VocabularyDatabase, args: argparse.Namespace) -> list:
    episodes = [args.episode] if args.episode is not None else args.episodes
    ids = db.source_ids(args.series, args.season, episodes)
    if len(ids) != len(episodes):
        raise KeyError("One or more selected episodes have not been imported")
    return ids


def _resolve_path(base: Path, value: Optional[str]) -> Optional[Path]:
    if value is None:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _subtitle_for_episode(
    *, video: Optional[Path], srt: Optional[Path], track: Optional[int],
    cache: Path, language: str,
) -> Optional[Path]:
    if srt:
        return srt
    if track is None:
        return None
    if video is None:
        raise ValueError(f"A video is required to extract the {language} subtitle track")
    destination = cache / f"{language}.srt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    extract_subtitle_stream(video, track, destination)
    return destination


def _ingest(
    db: VocabularyDatabase, *, series: str, season: int, episode: int,
    title: Optional[str], video: Optional[Path], ja_srt: Optional[Path],
    en_srt: Optional[Path], ja_track: Optional[int], en_track: Optional[int],
    tokenizer: JapaneseTokenizer,
) -> dict:
    cache = Path(".vocabdeck/subtitles") / re.sub(r"[^A-Za-z0-9._-]+", "_", series) / f"S{season:02d}E{episode:02d}"
    japanese_path = _subtitle_for_episode(
        video=video, srt=ja_srt, track=ja_track, cache=cache, language="ja"
    )
    english_path = _subtitle_for_episode(
        video=video, srt=en_srt, track=en_track, cache=cache, language="en"
    )
    if japanese_path is None:
        raise ValueError("Select Japanese subtitles with --ja-srt or --ja-track")
    japanese = merge_continuations(read_srt(japanese_path))
    english = read_srt(english_path) if english_path else []
    source_id = db.add_source(
        series=series, season=season, episode=episode, title=title,
        video_path=str(video.resolve()) if video else None,
        japanese_subtitle_path=str(japanese_path.resolve()),
        english_subtitle_path=str(english_path.resolve()) if english_path else None,
    )
    return {"source_id": source_id, **db.ingest_cues(source_id, japanese, english, tokenizer)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vocabdeck")
    parser.add_argument("--db", default="vocabdeck.sqlite3", help="SQLite state database")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize the state database")

    probe = commands.add_parser("probe", help="List embedded subtitle tracks")
    probe.add_argument("video", type=Path)

    ingest = commands.add_parser("ingest", help="Ingest one episode from SRT files or embedded tracks")
    ingest.add_argument("--series", required=True)
    ingest.add_argument("--season", required=True, type=int)
    ingest.add_argument("--episode", required=True, type=int)
    ingest.add_argument("--title")
    ingest.add_argument("--video", type=Path)
    ja = ingest.add_mutually_exclusive_group(required=True)
    ja.add_argument("--ja-srt", type=Path)
    ja.add_argument("--ja-track", type=int, help="absolute ffprobe stream index")
    en = ingest.add_mutually_exclusive_group()
    en.add_argument("--en-srt", type=Path)
    en.add_argument("--en-track", type=int, help="absolute ffprobe stream index")

    manifest = commands.add_parser("ingest-manifest", help="Ingest a selected episode range from JSON")
    manifest.add_argument("manifest", type=Path)
    manifest.add_argument("--episodes", required=True, type=_episode_selection)

    queue = commands.add_parser("queue", help="Preview globally unseen words for selected episodes")
    _source_selector(queue)
    queue.add_argument("--limit", type=int, default=20)
    queue.add_argument("--metric", choices=METRICS, default="hybrid")

    compare = commands.add_parser("compare-difficulty", help="Compare candidate rankings")
    _source_selector(compare)
    compare.add_argument("--limit", type=int, default=15)

    enrich = commands.add_parser("enrich-dictionary", help="Add offline JMdict glosses")
    _source_selector(enrich)
    enrich.add_argument("--force", action="store_true")

    preview = commands.add_parser("export-preview", help="Render cards to standalone HTML")
    _source_selector(preview)
    preview.add_argument("--limit", type=int, default=20)
    preview.add_argument("--metric", choices=METRICS, default="hybrid")
    preview.add_argument("--output", required=True, type=Path)
    preview.add_argument("--no-media", action="store_true")

    audit = commands.add_parser(
        "audit", help="Render a quality report for the next Anki batch"
    )
    _source_selector(audit)
    audit.add_argument("--limit", type=int, default=100)
    audit.add_argument("--metric", choices=METRICS, default="hybrid")
    audit.add_argument("--output", required=True, type=Path)

    known = commands.add_parser("mark-known", help="Mark a canonical lexeme as globally studied")
    known.add_argument("lexeme_key")
    sync = commands.add_parser("sync-anki", help="Pull learned state and add the next source batch")
    _source_selector(sync)
    sync.add_argument("--limit", type=int, default=20)
    sync.add_argument("--metric", choices=METRICS, default="hybrid")
    commands.add_parser("stats", help="Show corpus and learning-state counts")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "probe":
        print(json.dumps(probe_subtitle_streams(args.video), ensure_ascii=False, indent=2))
        return 0

    db = _database(args.db)
    try:
        if args.command == "init":
            print(f"Initialized {db.path}")
        elif args.command == "ingest":
            result = _ingest(
                db, series=args.series, season=args.season, episode=args.episode,
                title=args.title, video=args.video, ja_srt=args.ja_srt,
                en_srt=args.en_srt, ja_track=args.ja_track, en_track=args.en_track,
                tokenizer=_semantic_tokenizer(),
            )
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "ingest-manifest":
            manifest_path = args.manifest.resolve()
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            selected = set(args.episodes)
            tokenizer = _semantic_tokenizer()
            results = []
            for item in data["episodes"]:
                episode = int(item["episode"])
                if episode not in selected:
                    continue
                video = _resolve_path(manifest_path.parent, item.get("video"))
                japanese = item.get("japanese", {})
                english = item.get("english", {})
                results.append(_ingest(
                    db, series=data["series"], season=int(data.get("season", 1)),
                    episode=episode, title=item.get("title"), video=video,
                    ja_srt=_resolve_path(manifest_path.parent, japanese.get("srt")),
                    en_srt=_resolve_path(manifest_path.parent, english.get("srt")),
                    ja_track=japanese.get("track"), en_track=english.get("track"),
                    tokenizer=tokenizer,
                ))
            missing = selected - {int(item["episode"]) for item in data["episodes"]}
            if missing:
                raise KeyError(f"Episodes missing from manifest: {sorted(missing)}")
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif args.command == "queue":
            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            rows = db.next_unseen_for_sources(source_ids, args.limit, args.metric)
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif args.command == "compare-difficulty":
            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            comparison = {}
            for metric in METRICS:
                rows = db.next_unseen_for_sources(source_ids, args.limit, metric)
                comparison[metric] = [
                    {
                        "word": row["lemma"], "reading": row["reading"],
                        "score": row["difficulty_score"],
                        "zipf": row["difficulty_breakdown"]["general_zipf"],
                        "source_count": row["source_count"],
                        "gloss": row.get("gloss"),
                        "sentence": row["japanese"], "english": row["english"],
                    }
                    for row in rows
                ]
            print(json.dumps(comparison, ensure_ascii=False, indent=2))
        elif args.command == "enrich-dictionary":
            source_ids = _selected_source_ids(db, args)
            result = db.enrich_dictionary(source_ids, force=args.force)
            print(json.dumps(result, indent=2))
        elif args.command == "export-preview":
            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            rows = db.next_unseen_for_sources(source_ids, args.limit, args.metric)
            output = render_preview_html(rows, args.output, include_media=not args.no_media)
            print(str(output))
        elif args.command == "audit":
            from .audit import audit_queue, render_audit_html

            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            report = audit_queue(db, source_ids, args.limit, args.metric)
            output = render_audit_html(report, args.output)
            print(json.dumps({"output": str(output), **report["summary"]}, indent=2))
        elif args.command == "mark-known":
            db.mark_known(args.lexeme_key)
            print(f"Marked known: {args.lexeme_key}")
        elif args.command == "sync-anki":
            source_ids = _selected_source_ids(db, args)
            enrichment = db.enrich_dictionary(source_ids)
            result = sync_source(db, source_ids, limit=args.limit, metric=args.metric)
            result["dictionary"] = enrichment
            print(json.dumps(result, indent=2))
        elif args.command == "stats":
            print(json.dumps(db.stats(), indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
