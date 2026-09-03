from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Optional, Sequence

from .database import VocabularyDatabase
from .anki import sync_source
from .audit import AUDIT_CRITERION_CODES
from .difficulty import METRICS
from .media import extract_subtitle_stream, probe_subtitle_streams
from .manifest import build_manifest
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

    build_manifest_command = commands.add_parser(
        "build-manifest", help="Discover consistently named episode video/SRT pairs"
    )
    build_manifest_command.add_argument("directory", type=Path)
    build_manifest_command.add_argument("--series", required=True)
    build_manifest_command.add_argument("--season", type=int, default=1)
    build_manifest_command.add_argument("--episodes", required=True, type=_episode_selection)
    build_manifest_command.add_argument("--english-track", type=int, default=2)
    build_manifest_command.add_argument("--output", required=True, type=Path)

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
    manifest.add_argument(
        "--skip-existing", action="store_true",
        help="resume an import without replacing episodes already in the database",
    )

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
    audit.add_argument("--json-output", type=Path)
    audit.add_argument("--csv-output", type=Path)

    clean_preview = commands.add_parser(
        "export-clean-preview",
        help="Render only warning-free cards, dropping questionable samples",
    )
    _source_selector(clean_preview)
    clean_preview.add_argument("--limit", type=int, default=200)
    clean_preview.add_argument("--candidate-limit", type=int)
    clean_preview.add_argument("--metric", choices=METRICS, default="hybrid")
    clean_preview.add_argument("--output", required=True, type=Path)
    clean_preview.add_argument("--audit-output", required=True, type=Path)
    clean_preview.add_argument("--selection-output", required=True, type=Path)
    clean_preview.add_argument("--no-media", action="store_true")

    plan_calibration = commands.add_parser(
        "plan-calibration", help="Materialize a stable large review batch"
    )
    _source_selector(plan_calibration)
    plan_calibration.add_argument("--name", required=True)
    plan_calibration.add_argument("--limit", required=True, type=int)
    plan_calibration.add_argument("--metric", choices=METRICS, default="hybrid")
    plan_calibration.add_argument("--replace", action="store_true")

    audit_calibration = commands.add_parser(
        "audit-calibration", help="Audit a materialized calibration batch"
    )
    audit_calibration.add_argument("--name", required=True)
    audit_calibration.add_argument("--output", required=True, type=Path)
    audit_calibration.add_argument("--json-output", type=Path)
    audit_calibration.add_argument("--csv-output", type=Path)

    label_calibration = commands.add_parser(
        "label-calibration", help="Record a reviewer verdict for one criterion"
    )
    label_calibration.add_argument("--name", required=True)
    label_calibration.add_argument("--position", required=True, type=int)
    label_calibration.add_argument(
        "--criterion", required=True, choices=AUDIT_CRITERION_CODES
    )
    label_calibration.add_argument(
        "--verdict", required=True, choices=("pass", "flag", "uncertain")
    )
    label_calibration.add_argument("--note")

    import_reviews = commands.add_parser(
        "import-calibration-reviews",
        help="Import non-empty reviewer verdicts from an exported audit CSV",
    )
    import_reviews.add_argument("--name", required=True)
    import_reviews.add_argument("--input", required=True, type=Path)

    validation_candidates = commands.add_parser(
        "plan-validation-candidates",
        help="Freeze curriculum targets and audit several occurrences per word",
    )
    _source_selector(validation_candidates)
    validation_candidates.add_argument("--targets", type=int, default=200)
    validation_candidates.add_argument(
        "--candidates-per-target", type=int, default=5
    )
    validation_candidates.add_argument(
        "--metric", choices=METRICS, default="curriculum"
    )
    validation_candidates.add_argument("--output", required=True, type=Path)

    review_frontier = commands.add_parser(
        "plan-review-frontier",
        help="Plan only currently teachable occurrence reviews",
    )
    review_frontier.add_argument("--input", required=True, type=Path)
    review_frontier.add_argument("--selection", type=Path)
    review_frontier.add_argument("--contextual-reviews", type=Path)
    review_frontier.add_argument("--recoverability-reviews", type=Path)
    review_frontier.add_argument("--contextual-gloss-reviews", type=Path)
    review_frontier.add_argument("--limit", type=int, default=40)
    review_frontier.add_argument("--frontier-size", type=int, default=100)
    review_frontier.add_argument("--zero-unknown-through", type=int, default=20)
    review_frontier.add_argument("--one-unknown-through", type=int, default=200)
    review_frontier.add_argument("--max-unknown-later", type=int, default=2)
    review_frontier.add_argument("--output", required=True, type=Path)

    local_review = commands.add_parser(
        "review-calibration-local",
        help="Review an audit JSON with a resumable local MLX language model",
    )
    local_review.add_argument("--input", required=True, type=Path)
    local_review.add_argument("--output", required=True, type=Path)
    local_review.add_argument(
        "--model", required=True,
        help=(
            "Explicit MLX model repository or path. The frozen Qwen 9B "
            "baseline remains a comparison artifact, not a safe runtime "
            "default."
        ),
    )
    local_review.add_argument("--batch-size", type=int, default=4)
    local_review.add_argument("--max-tokens", type=int, default=48)
    local_review.add_argument("--max-kv-size", type=int, default=1024)
    local_review.add_argument(
        "--memory-limit-gb", type=float, default=4.0,
        help="MLX allocation limit (hard maximum: 6 GiB)",
    )
    local_review.add_argument("--limit", type=int)
    local_review.add_argument("--minimal-only", action="store_true")
    local_review.add_argument(
        "--max-per-target", type=int,
        help="Review only the best N occurrence candidates for each fixed target",
    )
    local_review.add_argument(
        "--deterministic-clean-only", action="store_true",
        help="Review only cards that pass every deterministic production gate",
    )
    local_review.add_argument(
        "--review-pass", choices=(
            "contextual", "critic", "recoverability", "contextual_gloss",
        ),
        default="contextual",
    )
    local_review.add_argument(
        "--thinking", action="store_true",
        help="Enable the model's slower reasoning mode",
    )

    small_benchmark = commands.add_parser(
        "benchmark-small-verifier",
        help="Benchmark a constrained small MLX verifier against 9B reviews",
    )
    small_benchmark.add_argument("--input", required=True, type=Path)
    small_benchmark.add_argument(
        "--contextual-reviews", required=True, type=Path
    )
    small_benchmark.add_argument(
        "--recoverability-reviews", required=True, type=Path
    )
    small_benchmark.add_argument(
        "--contextual-gloss-reviews", required=True, type=Path
    )
    small_benchmark.add_argument(
        "--model", default="mlx-community/Qwen3.5-2B-OptiQ-4bit"
    )
    small_benchmark.add_argument("--limit", type=int)
    small_benchmark.add_argument("--series")
    small_benchmark.add_argument("--episodes")
    small_benchmark.add_argument("--precision-target", type=float, default=0.995)
    small_benchmark.add_argument(
        "--memory-limit-gb", type=float, default=4.0,
        help="MLX allocation limit (hard maximum: 6 GiB)",
    )
    small_benchmark.add_argument("--output", required=True, type=Path)

    gold_dataset = commands.add_parser(
        "build-verifier-gold-dataset",
        help="Build frozen human-gold and review-queue verifier data",
    )
    gold_dataset.add_argument("--baseline", required=True, type=Path)
    gold_dataset.add_argument("--human-review", required=True, type=Path)
    gold_dataset.add_argument("--heldout-hxh", required=True, type=Path)
    gold_dataset.add_argument("--second-show", required=True, type=Path)
    gold_dataset.add_argument("--queue-size", type=int, default=40)
    gold_dataset.add_argument("--output", required=True, type=Path)

    evaluate_verifier = commands.add_parser(
        "evaluate-verifier-benchmark",
        help="Evaluate verifier predictions against human gold",
    )
    evaluate_verifier.add_argument("--dataset", required=True, type=Path)
    evaluate_verifier.add_argument("--predictions", required=True, type=Path)
    evaluate_verifier.add_argument("--precision-target", type=float, default=0.995)
    evaluate_verifier.add_argument("--minimum-accepted-gold", type=int, default=600)
    evaluate_verifier.add_argument(
        "--allow-prompt-version-override", action="store_true",
        help="Compare a versioned prompt experiment on the same frozen cases",
    )
    evaluate_verifier.add_argument("--json-output", required=True, type=Path)
    evaluate_verifier.add_argument("--html-output", required=True, type=Path)

    run_verifier = commands.add_parser(
        "run-verifier-benchmark",
        help="Run the constrained MLX verifier on a versioned dataset",
    )
    run_verifier.add_argument("--dataset", required=True, type=Path)
    run_verifier.add_argument(
        "--model", default="mlx-community/Qwen3.5-2B-OptiQ-4bit"
    )
    run_verifier.add_argument("--revision", required=True)
    run_verifier.add_argument(
        "--prompt-version", type=int, choices=(1, 2), default=1,
        help="Versioned constrained prompt policy (default: frozen v1)",
    )
    run_verifier.add_argument(
        "--memory-limit-gb", type=float, default=4.0,
        help="MLX allocation limit (hard maximum: 6 GiB)",
    )
    run_verifier.add_argument("--output", required=True, type=Path)

    smoke_verifier = commands.add_parser(
        "build-verifier-smoke-dataset",
        help="Build the deterministic gold-only verifier smoke cohort",
    )
    smoke_verifier.add_argument("--dataset", required=True, type=Path)
    smoke_verifier.add_argument("--size", type=int, default=20)
    smoke_verifier.add_argument("--output", required=True, type=Path)

    compare_verifiers = commands.add_parser(
        "compare-verifier-benchmarks",
        help="Build a fail-closed comparison from evaluated candidates",
    )
    compare_verifiers.add_argument("--config", required=True, type=Path)
    compare_verifiers.add_argument(
        "--evaluation", required=True, action="append", type=Path
    )
    compare_verifiers.add_argument("--output", required=True, type=Path)

    validate_reviewed = commands.add_parser(
        "validate-reviewed-cards",
        help="Apply deterministic, contextual, and recoverability gates",
    )
    validate_reviewed.add_argument("--input", required=True, type=Path)
    validate_reviewed.add_argument(
        "--contextual-reviews", required=True, type=Path
    )
    validate_reviewed.add_argument(
        "--recoverability-reviews", required=True, type=Path
    )
    validate_reviewed.add_argument(
        "--contextual-gloss-reviews", required=True, type=Path
    )
    validate_reviewed.add_argument("--output", required=True, type=Path)
    validate_reviewed.add_argument("--minimal-only", action="store_true")

    select_validated = commands.add_parser(
        "select-validated-curriculum",
        help="Choose one unanimously approved occurrence per fixed target",
    )
    select_validated.add_argument("--input", required=True, type=Path)
    select_validated.add_argument("--validation", required=True, type=Path)
    select_validated.add_argument("--output", required=True, type=Path)
    select_validated.add_argument("--preview", type=Path)
    select_validated.add_argument("--no-media", action="store_true")
    select_validated.add_argument("--limit", type=int)
    select_validated.add_argument(
        "--frontier-size", type=int, default=100,
        help="Maximum lexical-priority window considered at each teaching step",
    )
    select_validated.add_argument(
        "--zero-unknown-through", type=int, default=20,
    )
    select_validated.add_argument(
        "--one-unknown-through", type=int, default=200,
    )
    select_validated.add_argument(
        "--max-unknown-later", type=int, default=2,
    )

    compare_baseline = commands.add_parser(
        "compare-baseline",
        help="Compare a candidate curriculum with a frozen card baseline",
    )
    compare_baseline.add_argument(
        "--baseline", required=True, type=Path,
        help="baseline directory or expected-cards JSON file",
    )
    compare_baseline.add_argument("--candidate", required=True, type=Path)
    compare_baseline.add_argument("--human-review", type=Path)
    compare_baseline.add_argument("--json-output", required=True, type=Path)
    compare_baseline.add_argument("--html-output", required=True, type=Path)

    audio_review = commands.add_parser(
        "review-audio-cards",
        help="Fail-closed kana/audio validation before curriculum acceptance",
    )
    audio_review.add_argument("--input", required=True, type=Path)
    audio_review.add_argument("--output", required=True, type=Path)
    audio_review.add_argument("--preview", type=Path)
    audio_review.add_argument("--no-media", action="store_true")
    audio_review.add_argument(
        "--cache-directory", type=Path,
        default=Path(".vocabdeck/audio-review"),
    )
    audio_review.add_argument(
        "--positions", type=_episode_selection,
        help="optional 1-based artifact positions, e.g. 14,18,56",
    )
    audio_review.add_argument("--limit", type=int)
    audio_review.add_argument("--device", choices=("mps", "cpu"))

    coverage = commands.add_parser(
        "coverage", help="Report cumulative eligible vocabulary by episode"
    )
    coverage.add_argument("--series", required=True)
    coverage.add_argument("--season", required=True, type=int)
    coverage.add_argument("--output", type=Path)

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
    if args.command == "build-manifest":
        output = build_manifest(
            args.directory, args.output, series=args.series, season=args.season,
            episodes=args.episodes, english_track=args.english_track,
        )
        print(str(output))
        return 0
    if args.command == "review-calibration-local":
        from .local_review import (
            MLXBatchReviewer, load_review_cards, run_local_review,
        )

        cards = load_review_cards(args.input, minimal_only=args.minimal_only)
        if args.deterministic_clean_only:
            from .validation import DeterministicCardValidator

            deterministic = DeterministicCardValidator()
            cards = [
                card for card in cards
                if deterministic.validate(card).status == "accepted"
            ]
        if args.max_per_target is not None:
            if args.max_per_target < 1:
                raise ValueError("max per target must be positive")
            counts = {}
            limited = []
            for card in cards:
                target = int(
                    card.get("curriculum_position")
                    or card.get("audit_position")
                )
                count = counts.get(target, 0)
                if count >= args.max_per_target:
                    continue
                counts[target] = count + 1
                limited.append(card)
            cards = limited
        reviewer = MLXBatchReviewer(
            args.model, max_tokens=args.max_tokens,
            max_kv_size=args.max_kv_size,
            memory_limit_gb=args.memory_limit_gb,
            review_pass=args.review_pass,
            thinking=args.thinking,
        )
        try:
            result = run_local_review(
                cards, args.output, reviewer,
                batch_size=args.batch_size, limit=args.limit,
                review_pass=args.review_pass,
            )
        finally:
            reviewer.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "plan-review-frontier":
        from .local_review import load_review_cards, load_review_records
        from .validation import plan_review_frontier, write_validation_report

        cards = load_review_cards(args.input)
        selected_cards = []
        if args.selection:
            selection = json.loads(
                args.selection.expanduser().resolve().read_text(encoding="utf-8")
            )
            selected_cards = list(selection.get("accepted", []))
        reviews_by_pass = {}
        for review_pass, path in (
            ("contextual", args.contextual_reviews),
            ("recoverability", args.recoverability_reviews),
            ("contextual_gloss", args.contextual_gloss_reviews),
        ):
            if path and path.expanduser().resolve().exists():
                reviews_by_pass[review_pass] = load_review_records(path)
        plan = plan_review_frontier(
            cards,
            selected_cards=selected_cards,
            reviews_by_pass=reviews_by_pass,
            limit=args.limit,
            frontier_size=args.frontier_size,
            zero_unknown_through=args.zero_unknown_through,
            one_unknown_through=args.one_unknown_through,
            later_unknown_limit=args.max_unknown_later,
        )
        output = write_validation_report(plan, args.output)
        print(json.dumps({
            "output": str(output), **plan["summary"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "benchmark-small-verifier":
        from .constrained_review import (
            MLXLabelReviewer, run_constrained_benchmark, teacher_labels,
        )
        from .local_review import load_review_cards

        cards = load_review_cards(args.input)
        if args.series:
            cards = [
                card for card in cards
                if str(card.get("series") or "") == args.series
            ]
        if args.episodes:
            episodes = set(_episode_selection(args.episodes))
            cards = [
                card for card in cards
                if int(card.get("episode") or 0) in episodes
            ]
        labels = teacher_labels(
            args.contextual_reviews,
            args.recoverability_reviews,
            args.contextual_gloss_reviews,
        )
        cards = [
            card for card in cards if int(card["audit_position"]) in labels
        ]
        if args.limit is not None:
            cards = cards[:max(0, int(args.limit))]
        reviewer = MLXLabelReviewer(
            args.model, memory_limit_gb=args.memory_limit_gb
        )
        try:
            result = run_constrained_benchmark(
                cards, reviewer, labels,
                precision_target=args.precision_target,
            )
        finally:
            reviewer.close()
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "output": str(output), **result["summary"]
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "build-verifier-smoke-dataset":
        from .gold_benchmark import write_json
        from .small_verifier_benchmark import build_smoke_dataset

        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        smoke = build_smoke_dataset(dataset, args.size)
        output = write_json(smoke, args.output)
        print(json.dumps({
            "output": str(output),
            "cases": sum(len(rows) for rows in smoke["splits"].values()),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "compare-verifier-benchmarks":
        from .gold_benchmark import write_json
        from .small_verifier_benchmark import (
            build_comparison_report, load_candidate_config,
        )

        evaluations = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in args.evaluation
        ]
        comparison = build_comparison_report(
            evaluations, load_candidate_config(args.config)
        )
        output = write_json(comparison, args.output)
        print(json.dumps({
            "output": str(output),
            "recommendation": comparison["recommendation"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "build-verifier-gold-dataset":
        from .gold_benchmark import build_gold_dataset, write_json

        dataset = build_gold_dataset(
            args.baseline, args.human_review, args.heldout_hxh,
            args.second_show, queue_size=args.queue_size,
        )
        output = write_json(dataset, args.output)
        print(json.dumps({
            "output": str(output),
            "splits": {
                name: len(rows) for name, rows in dataset["splits"].items()
            },
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "evaluate-verifier-benchmark":
        from .gold_benchmark import (
            evaluate_predictions, render_blinded_html, write_json,
        )

        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        report = evaluate_predictions(
            dataset, predictions, precision_target=args.precision_target,
            minimum_accepted_gold=args.minimum_accepted_gold,
            allow_prompt_version_override=args.allow_prompt_version_override,
        )
        json_output = write_json(report, args.json_output)
        html_output = render_blinded_html(dataset, report, args.html_output)
        print(json.dumps({
            "json_output": str(json_output),
            "html_output": str(html_output),
            **report["summary"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run-verifier-benchmark":
        from .constrained_review import MLXLabelReviewer, run_constrained_dataset
        from .gold_benchmark import validate_dataset, write_json

        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        validate_dataset(dataset)
        reviewer = MLXLabelReviewer(
            args.model, revision=args.revision,
            memory_limit_gb=args.memory_limit_gb,
        )
        try:
            predictions = run_constrained_dataset(
                dataset, reviewer, prompt_version=args.prompt_version,
            )
        finally:
            reviewer.close()
        from .inference_resources import InferenceResourceGuard
        cleanup_probe = InferenceResourceGuard()
        cleanup_probe.acquire()
        cleanup_probe.release()
        predictions["summary"]["cleanup_verified"] = True
        output = write_json(predictions, args.output)
        print(json.dumps({
            "output": str(output), **predictions["summary"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate-reviewed-cards":
        from .local_review import load_review_cards, load_review_records
        from .validation import (
            DeterministicCardValidator, RecordedReviewValidator,
            UnanimousCardValidator, validate_cards, write_validation_report,
        )

        cards = load_review_cards(args.input, minimal_only=args.minimal_only)
        validator = UnanimousCardValidator([
            DeterministicCardValidator(),
            RecordedReviewValidator(
                "contextual", load_review_records(args.contextual_reviews)
            ),
            RecordedReviewValidator(
                "recoverability",
                load_review_records(args.recoverability_reviews),
            ),
            RecordedReviewValidator(
                "contextual_gloss",
                load_review_records(args.contextual_gloss_reviews),
            ),
        ])
        report = validate_cards(cards, validator)
        output = write_validation_report(report, args.output)
        print(json.dumps({
            "output": str(output), **report["summary"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "select-validated-curriculum":
        from .local_review import load_review_cards
        from .validation import (
            select_validated_curriculum, write_validation_report,
        )

        cards = load_review_cards(args.input)
        validation_report = json.loads(
            args.validation.expanduser().resolve().read_text(encoding="utf-8")
        )
        selection = select_validated_curriculum(
            cards, validation_report,
            frontier_size=args.frontier_size,
            zero_unknown_through=args.zero_unknown_through,
            one_unknown_through=args.one_unknown_through,
            later_unknown_limit=args.max_unknown_later,
            limit=args.limit,
        )
        output = write_validation_report(selection, args.output)
        preview = None
        if args.preview:
            preview = render_preview_html(
                selection["accepted"], args.preview,
                include_media=not args.no_media,
            )
        print(json.dumps({
            "output": str(output),
            "preview": None if preview is None else str(preview),
            **selection["summary"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "compare-baseline":
        from .comparison import (
            compare_card_sets, load_card_artifact, render_comparison_html,
            write_comparison_json,
        )

        baseline_path = args.baseline.expanduser().resolve()
        if baseline_path.is_dir():
            baseline_cards_path = baseline_path / "expected-cards.json"
            default_review_path = baseline_path / "human-review.json"
        else:
            baseline_cards_path = baseline_path
            default_review_path = baseline_path.parent / "human-review.json"
        review_path = (
            args.human_review.expanduser().resolve()
            if args.human_review else default_review_path
        )
        human_review = None
        if review_path.exists():
            human_review = json.loads(review_path.read_text(encoding="utf-8"))
        report = compare_card_sets(
            load_card_artifact(baseline_cards_path),
            load_card_artifact(args.candidate),
            human_review=human_review,
        )
        json_output = write_comparison_json(report, args.json_output)
        html_output = render_comparison_html(report, args.html_output)
        print(json.dumps({
            "json_output": str(json_output),
            "html_output": str(html_output),
            **report["summary"],
            "curriculum_passed": report["checks"][
                "curriculum_unknown_words"
            ]["passed"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "review-audio-cards":
        from .audio_validation import (
            AudioContentGate, HiraganaCTCTranscriber,
            MLXWhisperTranscriber, review_audio_cards,
        )
        from .comparison import load_card_artifact

        cards = load_card_artifact(args.input)
        if args.positions:
            selected = set(args.positions)
            cards = [
                card for position, card in enumerate(cards, start=1)
                if position in selected
            ]
        if args.limit is not None:
            if args.limit < 1:
                raise ValueError("limit must be positive")
            cards = cards[:args.limit]
        gate = AudioContentGate(
            HiraganaCTCTranscriber(device=args.device),
            orthographic_transcriber=MLXWhisperTranscriber(),
        )
        report = review_audio_cards(
            cards, gate, args.cache_directory.expanduser().resolve(),
            progress=lambda index, total, result: print(
                f"audio review {index}/{total}: {result['status']} "
                f"({result['reason']})", file=sys.stderr, flush=True,
            ),
        )
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        preview = None
        if args.preview:
            preview = render_preview_html(
                report["accepted"], args.preview,
                include_media=not args.no_media,
            )
        print(json.dumps({
            "output": str(output),
            "preview": None if preview is None else str(preview),
            **report["summary"],
        }, ensure_ascii=False, indent=2))
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
                if args.skip_existing and db.source_ids(
                    data["series"], int(data.get("season", 1)), [episode]
                ):
                    results.append({"episode": episode, "skipped": True})
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
            rows = db.next_unseen_sense_cards_for_sources(
                source_ids, args.limit, args.metric
            )
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif args.command == "compare-difficulty":
            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            comparison = {}
            for metric in METRICS:
                rows = db.next_unseen_sense_cards_for_sources(
                    source_ids, args.limit, metric
                )
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
            rows = db.next_unseen_sense_cards_for_sources(
                source_ids, args.limit, args.metric
            )
            output = render_preview_html(rows, args.output, include_media=not args.no_media)
            print(str(output))
        elif args.command == "audit":
            from .audit import (
                audit_queue, render_audit_html, write_audit_csv, write_audit_json,
            )

            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            report = audit_queue(db, source_ids, args.limit, args.metric)
            output = render_audit_html(report, args.output)
            if args.json_output:
                write_audit_json(report, args.json_output)
            if args.csv_output:
                write_audit_csv(report, args.csv_output)
            print(json.dumps({"output": str(output), **report["summary"]}, indent=2))
        elif args.command == "export-clean-preview":
            from .audit import (
                audit_queue, audit_rows, render_audit_html, select_clean_cards,
                write_audit_json,
            )

            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            candidate_limit = args.candidate_limit or max(
                args.limit + 100, args.limit * 2
            )
            candidate_report = audit_queue(
                db, source_ids, candidate_limit, args.metric
            )
            selection = select_clean_cards(
                db, candidate_report, args.limit,
                source_ids=source_ids, metric=args.metric,
            )
            if not selection["summary"]["complete"]:
                raise RuntimeError(
                    f"Only {selection['summary']['accepted']} clean cards were found "
                    f"among {candidate_limit} candidates"
                )
            accepted_report = audit_rows(
                db, selection["accepted"], metric=args.metric,
                source_ids=source_ids, excluded_limit=0,
            )
            if accepted_report["summary"]["cards_with_findings"]:
                raise RuntimeError("Accepted cards failed the final quality recheck")
            preview_output = render_preview_html(
                selection["accepted"], args.output,
                include_media=not args.no_media,
            )
            audit_output = render_audit_html(accepted_report, args.audit_output)
            selection_document = {
                **selection["summary"],
                "preview": str(preview_output),
                "audit": str(audit_output),
                "rejected": selection["rejected"],
            }
            write_audit_json(selection_document, args.selection_output)
            print(json.dumps(selection_document, ensure_ascii=False, indent=2))
        elif args.command == "plan-validation-candidates":
            from .audit import audit_rows, write_audit_json

            source_ids = _selected_source_ids(db, args)
            db.enrich_dictionary(source_ids)
            targets = db.sense_targets_for_sources(
                source_ids, args.targets, args.metric,
            )
            candidates = db.occurrence_candidates_for_targets(
                targets, source_ids,
                candidates_per_target=args.candidates_per_target,
            )
            report = audit_rows(db, candidates, metric=args.metric)
            report["curriculum"] = [
                {
                    "position": position,
                    "lexeme_id": int(card["lexeme_id"]),
                    "lexeme_key": str(card["lexeme_key"]),
                    "sense_key": str(card["sense_key"]),
                    "learning_unit_key": str(card["learning_unit_key"]),
                    "lemma": str(card["lemma"]),
                    "reading": str(card["reading"]),
                    "part_of_speech": str(card["part_of_speech"]),
                    "difficulty_score": float(card["difficulty_score"]),
                }
                for position, card in enumerate(targets, start=1)
            ]
            report["summary"].update({
                "curriculum_targets": len(targets),
                "occurrence_candidates": len(candidates),
                "candidates_per_target": int(args.candidates_per_target),
            })
            output = write_audit_json(report, args.output)
            print(json.dumps({
                "output": str(output), **report["summary"],
            }, ensure_ascii=False, indent=2))
        elif args.command == "plan-calibration":
            source_ids = _selected_source_ids(db, args)
            dictionary = db.enrich_dictionary(source_ids)
            result = db.create_calibration_batch(
                args.name, source_ids, args.limit, args.metric,
                replace=args.replace,
            )
            result["dictionary"] = dictionary
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "audit-calibration":
            from .audit import (
                attach_reviews, audit_rows, render_audit_html,
                write_audit_csv, write_audit_json,
            )

            batch = db.calibration_batch(args.name)
            report = audit_rows(
                db, batch["cards"], metric=batch["metric"],
                source_ids=batch["source_ids"],
                excluded_limit=min(batch["requested_limit"], 1000),
            )
            attach_reviews(report, db.calibration_reviews(args.name))
            output = render_audit_html(report, args.output)
            if args.json_output:
                write_audit_json(report, args.json_output)
            if args.csv_output:
                write_audit_csv(report, args.csv_output)
            print(json.dumps({
                "name": args.name, "output": str(output), **report["summary"],
            }, indent=2))
        elif args.command == "label-calibration":
            db.record_calibration_review(
                args.name, args.position, args.criterion, args.verdict, args.note,
            )
            print(json.dumps({
                "name": args.name,
                "position": args.position,
                "criterion": args.criterion,
                "verdict": args.verdict,
            }, ensure_ascii=False))
        elif args.command == "import-calibration-reviews":
            imported = 0
            with args.input.expanduser().resolve().open(
                encoding="utf-8", newline=""
            ) as handle:
                for row in csv.DictReader(handle):
                    verdict = str(row.get("review_verdict") or "").strip()
                    if not verdict:
                        continue
                    db.record_calibration_review(
                        args.name,
                        int(row["position"]),
                        str(row["criterion"]),
                        verdict,
                        str(row.get("review_note") or "").strip() or None,
                    )
                    imported += 1
            print(json.dumps({"name": args.name, "imported": imported}, indent=2))
        elif args.command == "coverage":
            source_ids = db.source_ids(args.series, args.season)
            db.enrich_dictionary(source_ids)
            growth = db.vocabulary_growth(args.series, args.season)
            document = json.dumps(growth, ensure_ascii=False, indent=2)
            if args.output:
                output = args.output.expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(document + "\n", encoding="utf-8")
                print(json.dumps({
                    "output": str(output),
                    "episodes": len(growth),
                    "final": growth[-1] if growth else None,
                }, ensure_ascii=False, indent=2))
            else:
                print(document)
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
