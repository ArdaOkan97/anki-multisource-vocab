from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple


PROMPT_VERSIONS = {
    "contextual": 5,
    "critic": 6,
    "recoverability": 1,
    "contextual_gloss": 1,
}
CONTEXTUAL_SYSTEM_PROMPT = """You are a strict reviewer of Japanese vocabulary flashcards.
Judge whether the exact target occurrence in the Japanese sentence is a good
example of the supplied dictionary sense for a learner. Check the local part of
speech, word boundaries, whether a larger expression dominates the meaning,
and whether the English subtitle supports the target sense. Reading is checked
by deterministic Japanese analyzers and is outside your task. A natural
idiomatic translation is acceptable only when it still demonstrates the target
word. Ordinary compositional combinations are valid; reject a larger expression
only when the target's supplied sense is not independently demonstrated. The
target's semantic contribution must be explicitly recoverable from the English
subtitle. Reject as not_recoverable when the translation omits or merely implies
the target meaning, even if the whole-sentence translation is natural. This is
especially important for pronouns, determiners, adverbs, and auxiliary-like
words. Return
only one compact JSON object with these keys:
{"verdict":"correct|incorrect|uncertain","reason_code":"supported|larger_expression|wrong_sense|wrong_segmentation|wrong_reading|subtitle_mismatch|not_recoverable|insufficient_context|other"}
Do not include analysis, markdown, confidence scores, or additional keys."""
CRITIC_SYSTEM_PROMPT = """You are a neutral independent verifier for a Japanese vocabulary flashcard.
Decide solely from the supplied evidence, avoiding both leniency and speculative
rejection. Check for a concrete incorrect word boundary, inflection, part of
speech, dictionary sense, larger fixed expression, name, sound effect, or
misleading subtitle. Reading is checked by deterministic Japanese analyzers and
is outside your task. Do not reject ordinary compositional combinations merely
because adjacent words form a common phrase. Reject as not_recoverable when the
English subtitle omits or merely implies the target's semantic contribution. A
generally correct whole-sentence translation is insufficient for a vocabulary
example. Return correct when the supplied sense is explicitly demonstrated and
there is no concrete contradiction.
Return only one compact JSON object with these keys:
{"verdict":"correct|incorrect|uncertain","reason_code":"supported|larger_expression|wrong_sense|wrong_segmentation|wrong_reading|subtitle_mismatch|not_recoverable|insufficient_context|other"}
Do not include analysis, markdown, confidence scores, or additional keys."""
RECOVERABILITY_SYSTEM_PROMPT = """You are checking one narrow property of a Japanese vocabulary example.
Decide whether the English subtitle explicitly expresses the marked Japanese
target's supplied dictionary meaning in this occurrence. The whole sentence
being a natural translation is not enough. Reject as not_recoverable when the
target meaning is omitted, absorbed into an insult, name, or fixed phrase, or
only inferable from the scene. Inflection and idiomatic English are allowed when
the target's semantic contribution remains clearly recoverable. Return only one
compact JSON object with these keys:
{"verdict":"correct|incorrect|uncertain","reason_code":"supported|not_recoverable|insufficient_context|other"}
Do not review reading, segmentation, or general subtitle quality. Do not include
analysis, markdown, confidence scores, or additional keys."""
CONTEXTUAL_GLOSS_SYSTEM_PROMPT = """You are checking one narrow property of a Japanese vocabulary example.
Judge whether the supplied English dictionary sense is an accurate,
learner-facing definition of the marked Japanese target in this exact sentence.
The definition must be specific enough to explain the occurrence; a related or
overly broad sense is insufficient. Treat possession, existence, copular,
temporal, directional, and idiomatic senses as distinct when Japanese usage does.
Inflection is allowed. Do not review reading, word segmentation, sentence
difficulty, or whether the full subtitle is natural. Return only one compact
JSON object with these keys:
{"verdict":"correct|incorrect|uncertain","reason_code":"supported|wrong_sense|insufficient_context|other"}
Do not include analysis, markdown, confidence scores, or additional keys."""
SYSTEM_PROMPTS = {
    "contextual": CONTEXTUAL_SYSTEM_PROMPT,
    "critic": CRITIC_SYSTEM_PROMPT,
    "recoverability": RECOVERABILITY_SYSTEM_PROMPT,
    "contextual_gloss": CONTEXTUAL_GLOSS_SYSTEM_PROMPT,
}

VERDICTS = {"correct", "incorrect", "uncertain"}
REASON_CODES = {
    "supported",
    "larger_expression",
    "wrong_sense",
    "wrong_segmentation",
    "wrong_reading",
    "subtitle_mismatch",
    "not_recoverable",
    "insufficient_context",
    "other",
    "invalid_output",
}


class BatchReviewer(Protocol):
    model_name: str

    def review(self, prompts: Sequence[str]) -> Tuple[List[str], Mapping[str, Any]]:
        ...


def card_prompt(card: Mapping[str, Any]) -> str:
    japanese = str(card.get("japanese") or "")
    target_start = card.get("target_start")
    target_end = card.get("target_end")
    if (
        isinstance(target_start, int)
        and isinstance(target_end, int)
        and 0 <= target_start < target_end <= len(japanese)
    ):
        japanese = (
            japanese[:target_start]
            + "⟦"
            + japanese[target_start:target_end]
            + "⟧"
            + japanese[target_end:]
        )
    return "\n".join([
        f"Target: {card.get('target_surface') or card.get('lemma') or ''}",
        f"Dictionary form: {card.get('lemma') or ''}",
        f"Part of speech: {card.get('part_of_speech') or ''}",
        f"Dictionary sense: {card.get('gloss') or ''}",
        f"Japanese sentence (target marked with ⟦ ⟧): {japanese}",
        f"English subtitle: {card.get('english') or ''}",
    ])


def card_fingerprint(
    card: Mapping[str, Any], *, review_pass: str = "contextual"
) -> str:
    if review_pass not in SYSTEM_PROMPTS:
        raise ValueError(f"unsupported review pass: {review_pass!r}")
    payload = {
        "position": card.get("audit_position"),
        "lexeme_key": card.get("lexeme_key"),
        "sense_key": card.get("sense_key"),
        "learning_unit_key": card.get("learning_unit_key"),
        "prompt": card_prompt(card),
        "prompt_version": PROMPT_VERSIONS[review_pass],
        "review_pass": review_pass,
    }
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_review_response(raw: str) -> Dict[str, str]:
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    value: Mapping[str, Any]
    if start >= 0 and end >= start:
        parsed = json.loads(text[start:end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("response JSON is not an object")
        value = parsed
    else:
        # Some local models emit the two requested fields first, then ignore the
        # compact-output instruction and hit the token cap while explaining.
        # Recover only complete, quoted enum fields; never infer missing values.
        verdict_match = re.search(r'"verdict"\s*:\s*"([^"\\]+)"', text)
        reason_match = re.search(r'"reason_code"\s*:\s*"([^"\\]+)"', text)
        if not verdict_match or not reason_match:
            raise ValueError("response does not contain complete review fields")
        value = {
            "verdict": verdict_match.group(1),
            "reason_code": reason_match.group(1),
        }
    verdict = str(value.get("verdict") or "").strip().lower()
    reason_code = str(value.get("reason_code") or "").strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"unsupported verdict: {verdict!r}")
    if reason_code not in REASON_CODES - {"invalid_output"}:
        raise ValueError(f"unsupported reason code: {reason_code!r}")
    if verdict == "correct" and reason_code != "supported":
        raise ValueError("correct verdict must use the supported reason")
    if verdict != "correct" and reason_code == "supported":
        raise ValueError("only a correct verdict may use the supported reason")
    return {"verdict": verdict, "reason_code": reason_code}


def load_review_cards(
    input_path: Path, *, minimal_only: bool = False
) -> List[Dict[str, Any]]:
    document = json.loads(input_path.expanduser().resolve().read_text(encoding="utf-8"))
    source = document.get("cards")
    if source is None:
        source = document.get("accepted", [])
    cards = [dict(card) for card in source]
    if minimal_only:
        cards = [
            card for card in cards
            if int((card.get("example_progression") or {}).get("content_words", 0))
            == 1
        ]
    return cards


def _existing_reviews(output_path: Path) -> Dict[int, Dict[str, Any]]:
    if not output_path.exists():
        return {}
    reviews: Dict[int, Dict[str, Any]] = {}
    with output_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                position = int(value["audit_position"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Invalid review JSONL at line {line_number}: {error}"
                ) from error
            reviews[position] = value
    return reviews


def load_review_records(input_path: Path) -> List[Dict[str, Any]]:
    """Load the latest append-only review for each audit position."""
    resolved = input_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    reviews = _existing_reviews(resolved)
    return [reviews[position] for position in sorted(reviews)]


def run_local_review(
    cards: Sequence[Mapping[str, Any]],
    output_path: Path,
    reviewer: BatchReviewer,
    *,
    batch_size: int = 4,
    limit: Optional[int] = None,
    review_pass: str = "contextual",
) -> Dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    if review_pass not in SYSTEM_PROMPTS:
        raise ValueError(f"unsupported review pass: {review_pass!r}")
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_reviews(output_path)
    selected_positions = {int(card["audit_position"]) for card in cards}
    selected_existing = {
        position: value
        for position, value in existing.items()
        if position in selected_positions
    }
    pending: List[Mapping[str, Any]] = []
    for card in cards:
        position = int(card["audit_position"])
        previous = existing.get(position)
        fingerprint = card_fingerprint(card, review_pass=review_pass)
        if previous:
            if previous.get("card_fingerprint") != fingerprint:
                raise ValueError(
                    f"Existing review at position {position} was created from different card data"
                )
            continue
        pending.append(card)
    if limit is not None:
        pending = pending[:max(0, int(limit))]

    verdict_counts: Counter[str] = Counter(
        str(value.get("verdict") or "") for value in selected_existing.values()
    )
    reason_counts: Counter[str] = Counter(
        str(value.get("reason_code") or "") for value in selected_existing.values()
    )
    invalid_outputs = 0
    reviewed_now = 0
    total_prompt_tokens = 0
    total_generation_tokens = 0
    total_prompt_time = 0.0
    total_generation_time = 0.0
    peak_memory = 0.0

    with output_path.open("a", encoding="utf-8") as handle:
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            raw_responses, stats = reviewer.review([card_prompt(card) for card in batch])
            if len(raw_responses) != len(batch):
                raise RuntimeError("reviewer returned a different number of responses")
            total_prompt_tokens += int(stats.get("prompt_tokens", 0))
            total_generation_tokens += int(stats.get("generation_tokens", 0))
            total_prompt_time += float(stats.get("prompt_time", 0.0))
            total_generation_time += float(stats.get("generation_time", 0.0))
            peak_memory = max(peak_memory, float(stats.get("peak_memory", 0.0)))
            timestamp = datetime.now(timezone.utc).isoformat()
            for card, raw in zip(batch, raw_responses):
                try:
                    parsed = parse_review_response(raw)
                except (ValueError, json.JSONDecodeError):
                    invalid_outputs += 1
                    parsed = {
                        "verdict": "uncertain",
                        "reason_code": "invalid_output",
                    }
                record = {
                    "schema_version": 1,
                    "prompt_version": PROMPT_VERSIONS[review_pass],
                    "review_pass": review_pass,
                    "model": reviewer.model_name,
                    "reviewed_at": timestamp,
                    "audit_position": int(card["audit_position"]),
                    "lexeme_key": str(card.get("lexeme_key") or ""),
                    "sense_key": str(card.get("sense_key") or ""),
                    "learning_unit_key": str(
                        card.get("learning_unit_key") or ""
                    ),
                    "lemma": str(card.get("lemma") or ""),
                    "reading": str(card.get("reading") or ""),
                    "part_of_speech": str(card.get("part_of_speech") or ""),
                    "gloss": str(card.get("gloss") or ""),
                    "japanese": str(card.get("japanese") or ""),
                    "english": str(card.get("english") or ""),
                    "series": str(card.get("series") or ""),
                    "season": card.get("season"),
                    "episode": card.get("episode"),
                    "gloss_score": card.get("gloss_score"),
                    "content_words": int(
                        (card.get("example_progression") or {}).get(
                            "content_words", 0
                        )
                    ),
                    "card_fingerprint": card_fingerprint(
                        card, review_pass=review_pass
                    ),
                    **parsed,
                    "raw_response": str(raw),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                verdict_counts[parsed["verdict"]] += 1
                reason_counts[parsed["reason_code"]] += 1
                reviewed_now += 1
            handle.flush()
            os.fsync(handle.fileno())

    completed = len(selected_existing) + reviewed_now
    return {
        "model": reviewer.model_name,
        "review_pass": review_pass,
        "selected": len(cards),
        "previously_reviewed": len(selected_existing),
        "reviewed_now": reviewed_now,
        "completed": completed,
        "remaining": max(0, len(cards) - completed),
        "invalid_outputs": invalid_outputs,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "prompt_tokens": total_prompt_tokens,
        "generation_tokens": total_generation_tokens,
        "prompt_tps": (
            round(total_prompt_tokens / total_prompt_time, 3)
            if total_prompt_time else None
        ),
        "generation_tps": (
            round(total_generation_tokens / total_generation_time, 3)
            if total_generation_time else None
        ),
        "peak_memory_gb": round(peak_memory, 3),
        "output": str(output_path),
    }


class MLXBatchReviewer:
    def __init__(
        self,
        model_name: str,
        *,
        max_tokens: int = 48,
        max_kv_size: int = 1024,
        memory_limit_gb: float = 4.0,
        review_pass: str = "contextual",
        thinking: bool = False,
    ) -> None:
        if review_pass not in SYSTEM_PROMPTS:
            raise ValueError(f"unsupported review pass: {review_pass!r}")
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
        except ImportError as error:
            self._resource_guard.release()
            raise RuntimeError(
                "Local review requires the local-review extra: "
                "uv sync --extra local-review"
            ) from error
        except Exception:
            self._resource_guard.release()
            raise
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.max_kv_size = max_kv_size
        self.review_pass = review_pass
        self.thinking = thinking
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

    def review(self, prompts: Sequence[str]) -> Tuple[List[str], Mapping[str, Any]]:
        encoded = [
            self._tokenizer.apply_chat_template(
                [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPTS[self.review_pass],
                    },
                    {"role": "user", "content": prompt},
                ],
                add_generation_prompt=True,
                enable_thinking=self.thinking,
            )
            for prompt in prompts
        ]
        response = self._batch_generate(
            self._model,
            self._tokenizer,
            encoded,
            max_tokens=self.max_tokens,
            max_kv_size=self.max_kv_size,
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
