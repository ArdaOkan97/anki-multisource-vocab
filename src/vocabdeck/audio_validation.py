from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
import wave
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from .database import canonical_sense_key, learning_unit_key
from .readings import ContextualReadingValidator
from .tokenizer import LexemeToken


CTC_MODEL_REPO = "sakasegawa/japanese-wav2vec2-large-hiragana-ctc"
CTC_MODEL_REVISION = "d30d246cd24a225821d03d183de7bb2e769e18df"
CTC_CHECKPOINT = "best-medium-ep5-inference.pt"
CTC_BASE_MODEL = "reazon-research/japanese-wav2vec2-large"
CTC_BASE_REVISION = "55969d3700533972fcc4ff0e3747f0bc3c21e4c1"
WHISPER_MODEL_REPO = "mlx-community/whisper-large-v3-turbo"
WHISPER_MODEL_REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
CTC_BACKEND_VERSION = 4

# Vocabulary and dual-head architecture are adapted from nyosegawa/hiragana-asr
# (Apache-2.0): https://github.com/nyosegawa/hiragana-asr
KANA = list(
    "あいうえおかきくけこさしすせそたちつてとなにぬねの"
    "はひふへほまみむめもやゆよらりるれろわをん"
    "がぎぐげござじずぜぞだぢづでどばびぶべぼ"
    "ぱぴぷぺぽぁぃぅぇぉっゃゅょゎー"
)
PHONEMES = (
    "A", "E", "I", "N", "O", "U", "a", "b", "by", "ch", "cl",
    "d", "dy", "e", "f", "g", "gy", "h", "hy", "i", "j", "k",
    "ky", "m", "my", "n", "ny", "o", "p", "py", "r", "ry", "s",
    "sh", "t", "ts", "ty", "u", "v", "w", "y", "z",
)

_MULTI_SPEAKER = re.compile(
    r"(?:≪[^≫]+≫\s*){2,}|(?:《[^》]+》\s*){2,}|(?:^|\n)\s*(?:>>|＞＞|--|—)",
    re.MULTILINE,
)
_DROP_PUNCTUATION = re.compile(r"[\s\u3000、。？！?!…～〜「」『』（）()［］\[\]{}・:;\"'`≪≫《》]+")
_NON_KANA = re.compile(r"[^ぁ-ゖー]")
_GLOSS_WORD = re.compile(r"[a-z][a-z'-]+")


def hiragana(value: str) -> str:
    return "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char
        for char in value
    )


def katakana(value: str) -> str:
    return "".join(
        chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char
        for char in value
    )


@lru_cache(maxsize=100_000)
def text_to_hiragana(text: str) -> str:
    import pyopenjtalk

    cleaned = _DROP_PUNCTUATION.sub("", text)
    if not cleaned:
        return ""
    return _NON_KANA.sub(
        "", hiragana(str(pyopenjtalk.g2p(cleaned, kana=True) or ""))
    )


@dataclass(frozen=True)
class AudioToken:
    text: str
    start_ms: int
    end_ms: int
    confidence: float


@dataclass(frozen=True)
class AudioTranscript:
    kana: str
    phonemes: str
    duration_ms: int
    tokens: Tuple[AudioToken, ...]
    backend: str
    model: str
    model_revision: str
    device: str
    runtime: Optional[Dict[str, Any]] = None

    def as_dict(self) -> dict:
        value = asdict(self)
        value["tokens"] = [asdict(token) for token in self.tokens]
        return value


class AudioTranscriber(Protocol):
    def transcribe(self, audio: Path) -> AudioTranscript:
        ...


@dataclass(frozen=True)
class OrthographicTranscript:
    text: str
    duration_ms: int
    tokens: Tuple[AudioToken, ...]
    backend: str
    model: str
    model_revision: str
    runtime: Optional[Dict[str, Any]] = None

    def as_dict(self) -> dict:
        value = asdict(self)
        value["tokens"] = [asdict(token) for token in self.tokens]
        return value


class OrthographicTranscriber(Protocol):
    def transcribe(self, audio: Path) -> OrthographicTranscript:
        ...


class MLXWhisperTranscriber:
    """High-recall Japanese target/timestamp detector for Apple Silicon."""

    def __init__(
        self,
        *,
        model_repo: str = WHISPER_MODEL_REPO,
        model_revision: str = WHISPER_MODEL_REVISION,
    ) -> None:
        self.model_repo = model_repo
        self.model_revision = model_revision
        self._model_path: Optional[str] = None

    def transcribe(self, audio: Path) -> OrthographicTranscript:
        import mlx_whisper
        from huggingface_hub import snapshot_download

        if self._model_path is None:
            self._model_path = snapshot_download(
                self.model_repo, revision=self.model_revision
            )

        result = mlx_whisper.transcribe(
            str(audio),
            path_or_hf_repo=self._model_path,
            language="ja",
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        tokens = []
        for segment in result.get("segments", []):
            for word in segment.get("words", []):
                text = str(word.get("word") or "").strip()
                if not text:
                    continue
                start_ms = int(round(float(word.get("start") or 0) * 1000))
                end_ms = int(round(float(word.get("end") or 0) * 1000))
                confidence = float(word.get("probability") or 0)
                for char in text:
                    if _DROP_PUNCTUATION.fullmatch(char):
                        continue
                    tokens.append(AudioToken(
                        char, start_ms, end_ms, round(confidence, 4)
                    ))
        with wave.open(str(audio), "rb") as handle:
            duration_ms = int(round(
                handle.getnframes() * 1000 / handle.getframerate()
            ))
        return OrthographicTranscript(
            text="".join(token.text for token in tokens),
            duration_ms=duration_ms,
            tokens=tuple(tokens),
            backend="mlx-whisper",
            model=self.model_repo,
            model_revision=self.model_revision,
        )


class HiraganaCTCTranscriber:
    """Local, unprompted Japanese kana/phoneme CTC inference."""

    def __init__(
        self,
        *,
        model_repo: str = CTC_MODEL_REPO,
        model_revision: str = CTC_MODEL_REVISION,
        checkpoint_name: str = CTC_CHECKPOINT,
        device: Optional[str] = None,
    ) -> None:
        self.model_repo = model_repo
        self.model_revision = model_revision
        self.checkpoint_name = checkpoint_name
        self.requested_device = device
        self._runtime: Optional[Tuple[Any, Any, Any, str]] = None

    def _load(self) -> Tuple[Any, Any, Any, str]:
        if self._runtime is not None:
            return self._runtime
        import torch
        import torch.nn as nn
        from huggingface_hub import hf_hub_download
        from transformers import (
            Wav2Vec2Config, Wav2Vec2FeatureExtractor, Wav2Vec2Model,
        )

        checkpoint_path = hf_hub_download(
            self.model_repo,
            self.checkpoint_name,
            revision=self.model_revision,
        )
        checkpoint = torch.load(
            checkpoint_path, map_location="cpu", weights_only=True
        )
        pretrained = str(checkpoint.get("pretrained") or CTC_BASE_MODEL)
        config = Wav2Vec2Config.from_pretrained(
            pretrained, revision=CTC_BASE_REVISION
        )
        config.mask_time_prob = 0.0

        class DualCTCModel(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.encoder = Wav2Vec2Model(config)
                self.inter_ctc_layer = int(
                    checkpoint.get("inter_ctc_layer") or 12
                )
                self.kana_head = nn.Linear(config.hidden_size, len(KANA) + 1)
                self.phoneme_head = nn.Linear(
                    config.hidden_size, len(PHONEMES) + 1
                )

            def forward(self, input_values: Any, attention_mask: Any) -> dict:
                output = self.encoder(
                    input_values,
                    attention_mask=attention_mask,
                    output_hidden_states=True,
                )
                return {
                    "kana_logits": self.kana_head(output.last_hidden_state),
                    "phoneme_logits": self.phoneme_head(
                        output.hidden_states[self.inter_ctc_layer]
                    ),
                }

        model = DualCTCModel()
        incompatible = model.load_state_dict(
            checkpoint["model_state_dict"], strict=False
        )
        unexpected = set(incompatible.unexpected_keys)
        if incompatible.missing_keys or unexpected - {"encoder.masked_spec_embed"}:
            raise RuntimeError(
                "audio model checkpoint does not match the pinned architecture: "
                f"missing={incompatible.missing_keys}, "
                f"unexpected={incompatible.unexpected_keys}"
            )
        if self.requested_device:
            device = self.requested_device
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
        try:
            model.eval().to(device)
        except RuntimeError:
            if self.requested_device is not None or device != "mps":
                raise
            device = "cpu"
            model.eval().to(device)
        extractor = Wav2Vec2FeatureExtractor.from_pretrained(
            pretrained, revision=CTC_BASE_REVISION
        )
        self._runtime = (torch, model, extractor, device)
        return self._runtime

    @staticmethod
    def _waveform(audio: Path) -> Tuple[Any, int]:
        import numpy as np

        with wave.open(str(audio), "rb") as handle:
            if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                raise ValueError("audio gate requires mono 16-bit PCM WAV")
            rate = int(handle.getframerate())
            raw = handle.readframes(handle.getnframes())
        samples = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
        return samples, rate

    @staticmethod
    def _collapsed_tokens(
        logits: Any, vocabulary: Sequence[str], duration_ms: int
    ) -> Tuple[str, Tuple[AudioToken, ...]]:
        probabilities = logits.float().softmax(dim=-1)[0]
        values, indices = probabilities.max(dim=-1)
        frame_ms = duration_ms / max(1, int(indices.shape[0]))
        tokens: List[AudioToken] = []
        previous = 0
        active: Optional[Dict[str, Any]] = None
        for frame, (raw_index, raw_probability) in enumerate(
            zip(indices.tolist(), values.tolist())
        ):
            index = int(raw_index)
            if index == 0:
                if active is not None:
                    active["end_frame"] = frame
                    tokens.append(AudioToken(
                        active["text"],
                        int(round(active["start_frame"] * frame_ms)),
                        int(round(max(active["start_frame"] + 1, frame) * frame_ms)),
                        round(sum(active["probabilities"]) / len(active["probabilities"]), 4),
                    ))
                    active = None
                previous = 0
                continue
            text = vocabulary[index - 1]
            if index != previous:
                if active is not None:
                    tokens.append(AudioToken(
                        active["text"],
                        int(round(active["start_frame"] * frame_ms)),
                        int(round(frame * frame_ms)),
                        round(sum(active["probabilities"]) / len(active["probabilities"]), 4),
                    ))
                active = {
                    "text": text,
                    "start_frame": frame,
                    "probabilities": [float(raw_probability)],
                }
            elif active is not None:
                active["probabilities"].append(float(raw_probability))
            previous = index
        if active is not None:
            tokens.append(AudioToken(
                active["text"],
                int(round(active["start_frame"] * frame_ms)),
                duration_ms,
                round(sum(active["probabilities"]) / len(active["probabilities"]), 4),
            ))
        return "".join(token.text for token in tokens), tuple(tokens)

    @staticmethod
    def _collapsed_phonemes(logits: Any) -> str:
        indices = logits[0].argmax(dim=-1).tolist()
        output = []
        previous = 0
        for raw_index in indices:
            index = int(raw_index)
            if index and index != previous:
                output.append(PHONEMES[index - 1])
            previous = index
        return " ".join(output)

    def transcribe(self, audio: Path) -> AudioTranscript:
        torch, model, extractor, device = self._load()
        samples, sample_rate = self._waveform(audio)
        if sample_rate != 16_000:
            raise ValueError("audio gate requires 16 kHz WAV")
        duration_ms = int(round(len(samples) * 1000 / sample_rate))
        inputs = extractor(
            samples,
            sampling_rate=sample_rate,
            return_tensors="pt",
            return_attention_mask=True,
        )
        with torch.inference_mode():
            output = model(
                inputs.input_values.to(device),
                inputs.attention_mask.to(device),
            )
        kana, tokens = self._collapsed_tokens(
            output["kana_logits"].cpu(), KANA, duration_ms
        )
        phonemes = self._collapsed_phonemes(output["phoneme_logits"].cpu())
        return AudioTranscript(
            kana=kana,
            phonemes=phonemes,
            duration_ms=duration_ms,
            tokens=tokens,
            backend=f"hiragana-ctc-v{CTC_BACKEND_VERSION}",
            model=self.model_repo,
            model_revision=self.model_revision,
            device=device,
        )


@dataclass(frozen=True)
class ReadingAlternative:
    reading: str
    entry_id: Optional[int]
    sense_index: Optional[int]
    gloss: str
    contextual_reading: Optional[str] = None


class JMDictReadingAlternatives:
    def __init__(self) -> None:
        from jamdict import Jamdict

        self.dictionary = Jamdict()

    @staticmethod
    def _words(value: str) -> set:
        return set(_GLOSS_WORD.findall(value.lower()))

    @lru_cache(maxsize=100_000)
    def resolve(
        self, lemma: str, gloss: str, part_of_speech: str, reading: str
    ) -> Tuple[ReadingAlternative, ...]:
        selected_words = self._words(gloss)
        matches: Dict[str, ReadingAlternative] = {}
        result = self.dictionary.lookup(
            lemma, lookup_chars=False, lookup_ne=False
        )
        for entry in result.entries:
            spellings = [form.text for form in entry.kanji_forms]
            if lemma not in spellings:
                continue
            for sense_index, sense in enumerate(entry.senses):
                glosses = [
                    item.text for item in sense.gloss if item.lang in ("", "eng")
                ]
                candidate_gloss = "; ".join(glosses[:3])
                candidate_words = self._words(candidate_gloss)
                if selected_words and not selected_words.intersection(candidate_words):
                    continue
                for form in entry.kana_forms:
                    normalized = hiragana(form.text)
                    if normalized and normalized not in matches:
                        matches[normalized] = ReadingAlternative(
                            normalized, int(entry.idseq), sense_index,
                            candidate_gloss,
                        )
        current = hiragana(reading)
        if current and current not in matches:
            matches[current] = ReadingAlternative(current, None, None, gloss)
        return tuple(matches.values())


@dataclass(frozen=True)
class AudioGateConfig:
    narrow_padding_ms: int = 200
    expanded_padding_ms: int = 900
    boundary_margin_ms: int = 500
    output_margin_ms: int = 220
    minimum_sentence_coverage: float = 0.58
    minimum_target_confidence: float = 0.42
    maximum_working_window_ms: int = 12_000


@dataclass(frozen=True)
class AlignmentEvidence:
    reading: str
    sentence_coverage: float
    target_covered: bool
    target_confidence: float
    target_start_ms: Optional[int]
    target_end_ms: Optional[int]
    sentence_start_ms: Optional[int]
    sentence_end_ms: Optional[int]
    expected_kana: str

    def as_dict(self) -> dict:
        return asdict(self)


def _orthographic_alignment(
    card: Mapping[str, Any], transcript: OrthographicTranscript
) -> AlignmentEvidence:
    japanese = _DROP_PUNCTUATION.sub("", str(card.get("japanese") or ""))
    lexical_spans = card.get("target_lexical_spans") or []
    if lexical_spans:
        raw_start, raw_end = map(int, lexical_spans[0])
    else:
        raw_start = int(card.get("target_lexical_start") or 0)
        raw_end = int(card.get("target_lexical_end") or raw_start)
    raw_japanese = str(card.get("japanese") or "")
    prefix = _DROP_PUNCTUATION.sub("", raw_japanese[:raw_start])
    target = _DROP_PUNCTUATION.sub("", raw_japanese[raw_start:raw_end])
    observed = transcript.text
    matcher = SequenceMatcher(None, japanese, observed, autojunk=False)
    mapping: Dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    target_range = range(len(prefix), len(prefix) + len(target))
    target_indices = [mapping[index] for index in target_range if index in mapping]
    target_covered = (
        bool(target)
        and len(target_indices) == len(target)
        and target_indices == list(range(target_indices[0], target_indices[0] + len(target_indices)))
    )
    mapped_indices = sorted(mapping.values())
    target_tokens = [
        transcript.tokens[index] for index in target_indices
        if 0 <= index < len(transcript.tokens)
    ]
    sentence_tokens = [
        transcript.tokens[index] for index in mapped_indices
        if 0 <= index < len(transcript.tokens)
    ]
    return AlignmentEvidence(
        reading=str(card.get("reading") or ""),
        sentence_coverage=round(len(mapping) / max(1, len(japanese)), 4),
        target_covered=target_covered,
        target_confidence=round(
            min((token.confidence for token in target_tokens), default=0.0), 4
        ),
        target_start_ms=target_tokens[0].start_ms if target_covered else None,
        target_end_ms=target_tokens[-1].end_ms if target_covered else None,
        sentence_start_ms=sentence_tokens[0].start_ms if sentence_tokens else None,
        sentence_end_ms=sentence_tokens[-1].end_ms if sentence_tokens else None,
        expected_kana=japanese,
    )


def _align_candidate(
    card: Mapping[str, Any],
    transcript: AudioTranscript,
    alternative: ReadingAlternative,
) -> AlignmentEvidence:
    japanese = str(card.get("japanese") or "")
    lexical_spans = card.get("target_lexical_spans") or []
    if lexical_spans:
        start, end = map(int, lexical_spans[0])
    else:
        start = int(card.get("target_lexical_start") or card.get("target_start") or 0)
        end = int(card.get("target_lexical_end") or card.get("target_end") or start)
    prefix = text_to_hiragana(japanese[:start])
    suffix = text_to_hiragana(japanese[end:])
    occurrence_reading = alternative.contextual_reading or alternative.reading
    expected = prefix + occurrence_reading + suffix
    observed = transcript.kana
    matcher = SequenceMatcher(None, expected, observed, autojunk=False)
    mapping: Dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    target_range = range(len(prefix), len(prefix) + len(occurrence_reading))
    target_indices = [mapping[index] for index in target_range if index in mapping]
    target_covered = (
        bool(occurrence_reading)
        and len(target_indices) == len(occurrence_reading)
        and target_indices == list(range(target_indices[0], target_indices[0] + len(target_indices)))
    )
    mapped_indices = sorted(mapping.values())
    target_tokens = [
        transcript.tokens[index] for index in target_indices
        if 0 <= index < len(transcript.tokens)
    ]
    sentence_tokens = [
        transcript.tokens[index] for index in mapped_indices
        if 0 <= index < len(transcript.tokens)
    ]
    return AlignmentEvidence(
        reading=occurrence_reading,
        sentence_coverage=round(len(mapping) / max(1, len(expected)), 4),
        target_covered=target_covered,
        target_confidence=round(
            min((token.confidence for token in target_tokens), default=0.0), 4
        ),
        target_start_ms=target_tokens[0].start_ms if target_covered else None,
        target_end_ms=target_tokens[-1].end_ms if target_covered else None,
        sentence_start_ms=sentence_tokens[0].start_ms if sentence_tokens else None,
        sentence_end_ms=sentence_tokens[-1].end_ms if sentence_tokens else None,
        expected_kana=expected,
    )


def _audio_key(card: Mapping[str, Any], video: Path, config: AudioGateConfig) -> str:
    stat = video.stat()
    payload = {
        "card_snapshot": dict(card),
        "candidate_key": card.get("candidate_key"),
        "learning_unit_key": card.get("learning_unit_key"),
        "japanese": card.get("japanese"),
        "reading": card.get("reading"),
        "gloss": card.get("gloss"),
        "target_spans": card.get("target_lexical_spans"),
        "target_start": card.get("target_lexical_start", card.get("target_start")),
        "target_end": card.get("target_lexical_end", card.get("target_end")),
        "start_ms": card.get("start_ms"),
        "end_ms": card.get("end_ms"),
        "video": str(video.resolve()),
        "video_size": stat.st_size,
        "video_mtime_ns": stat.st_mtime_ns,
        "config": asdict(config),
        "backend_version": CTC_BACKEND_VERSION,
        "model_revision": CTC_MODEL_REVISION,
        "whisper_model_revision": WHISPER_MODEL_REVISION,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _extract_window(
    video: Path, start_ms: int, end_ms: int, destination: Path
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    start = max(0, start_ms) / 1000
    duration = max(0.4, end_ms - max(0, start_ms)) / 1000
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}",
            "-i", str(video), "-t", f"{duration:.3f}", "-vn", "-ac", "1",
            "-ar", "16000", "-c:a", "pcm_s16le", str(destination),
        ],
        check=True,
    )
    return destination


def _repaired_card(
    card: Mapping[str, Any],
    alternative: ReadingAlternative,
    evidence: Mapping[str, Any],
) -> dict:
    repaired = dict(card)
    original = str(card.get("reading") or "")
    selected = katakana(alternative.reading)
    identity = LexemeToken(
        surface=str(card.get("lemma") or ""),
        lemma=str(card.get("lemma") or ""),
        reading=selected,
        part_of_speech=str(card.get("part_of_speech") or ""),
    ).key
    sense_key = canonical_sense_key(
        alternative.entry_id,
        alternative.sense_index,
        str(card.get("part_of_speech") or ""),
        str(card.get("gloss") or ""),
    )
    repaired.update({
        "reading": selected,
        "lexeme_key": identity,
        "dictionary_entry_id": alternative.entry_id,
        "dictionary_sense_index": alternative.sense_index,
        "sense_key": sense_key,
        "learning_unit_key": learning_unit_key(identity, sense_key),
    })
    # This is an occurrence repair, not a global reading replacement. Update
    # only the marked target dependencies and never transfer old learned status.
    old_unit = str(card.get("learning_unit_key") or f"lexeme:{card.get('lexeme_id')}")
    new_unit = repaired["learning_unit_key"]
    from .validation import _context_learning_units, _initial_known_learning_units
    context = _context_learning_units(card)
    if context is not None:
        legacy_target = f"lexeme:{card.get('lexeme_id')}"
        repaired["context_learning_unit_keys"] = sorted((context - {old_unit, legacy_target}) | {new_unit})
        initial = _initial_known_learning_units(card)
        if initial is not None:
            repaired["initial_known_context_learning_unit_keys"] = sorted(initial)
    spans = {tuple(span) for span in card.get("target_lexical_spans", [])}
    if not spans:
        spans = {(card.get("target_lexical_start", card.get("target_start")),
                  card.get("target_lexical_end", card.get("target_end")))}
    if isinstance(card.get("context_meaning_dependencies"), list):
        dependencies = []
        for original_dependency in card["context_meaning_dependencies"]:
            dependency = dict(original_dependency)
            if (dependency.get("start"), dependency.get("end")) in spans:
                dependency["learning_unit_key"] = new_unit
                if "reading" in dependency:
                    dependency["reading"] = selected
            dependencies.append(dependency)
        repaired["context_meaning_dependencies"] = dependencies
        repaired["context_learning_unit_keys"] = sorted({d["learning_unit_key"] for d in dependencies})
    for field in ("lexeme_id", "note_id", "card_id", "last_seen_reps"):
        repaired[field] = None
    for field in ("context_lexeme_ids", "initial_known_context_lexeme_ids",
                  "initial_unknown_context_lexeme_ids", "validation", "reading_consensus"):
        repaired.pop(field, None)
    sentence_id = repaired.get("sentence_id")
    start = repaired.get("target_lexical_start", repaired.get("target_start"))
    end = repaired.get("target_lexical_end", repaired.get("target_end"))
    if (start is None or end is None) and repaired.get("target_lexical_spans"):
        start, end = repaired["target_lexical_spans"][0]
    if sentence_id is not None and start is not None and end is not None:
        repaired["candidate_key"] = ":".join((
            repaired["learning_unit_key"], str(sentence_id), str(start), str(end),
        ))
    repaired["audio_reading_repair"] = {
        "original_reading": original,
        "selected_reading": selected,
        **dict(evidence),
    }
    return repaired


class AudioContentGate:
    def __init__(
        self,
        transcriber: AudioTranscriber,
        *,
        config: AudioGateConfig = AudioGateConfig(),
        alternatives: Optional[JMDictReadingAlternatives] = None,
        reading_validator: Optional[ContextualReadingValidator] = None,
        orthographic_transcriber: Optional[OrthographicTranscriber] = None,
    ) -> None:
        self.transcriber = transcriber
        self.config = config
        self.alternatives = alternatives or JMDictReadingAlternatives()
        self.reading_validator = reading_validator or ContextualReadingValidator()
        self.orthographic_transcriber = orthographic_transcriber

    def review(
        self, card: Mapping[str, Any], cache_directory: Path
    ) -> dict:
        video = Path(str(card.get("video_path") or "")).expanduser()
        if not video.is_file():
            return self._rejected(card, "missing_video", [])
        key = _audio_key(card, video, self.config)
        record_path = cache_directory / "records" / f"{key}.json"
        if record_path.exists():
            return json.loads(record_path.read_text(encoding="utf-8"))
        if _MULTI_SPEAKER.search(str(card.get("japanese") or "")):
            result = self._rejected(card, "competing_speech_marker", [])
            return self._store(record_path, result)

        readings = self.alternatives.resolve(
            str(card.get("lemma") or ""),
            str(card.get("gloss") or ""),
            str(card.get("part_of_speech") or ""),
            str(card.get("reading") or ""),
        )
        if not readings:
            result = self._rejected(card, "no_compatible_readings", [])
            return self._store(record_path, result)
        start_ms = int(card["start_ms"])
        end_ms = int(card["end_ms"])
        lexical_spans = card.get("target_lexical_spans") or []
        if lexical_spans:
            lexical_start, lexical_end = map(int, lexical_spans[0])
        else:
            lexical_start = card.get("target_lexical_start")
            lexical_end = card.get("target_lexical_end")
        reading_consensus = self.reading_validator.validate(
            str(card.get("japanese") or ""), lexical_start,
            lexical_end, str(card.get("reading") or ""),
        ).as_dict()
        sudachi_reading = str(reading_consensus.get("sudachi") or "")
        openjtalk_reading = str(reading_consensus.get("openjtalk") or "")
        analyzers_agree = bool(
            sudachi_reading and sudachi_reading == openjtalk_reading
        )
        target_surface = str(card.get("japanese") or "")[
            int(lexical_start or 0):int(lexical_end or 0)
        ]
        is_inflected_surface = target_surface != str(card.get("lemma") or "")
        expected_dictionary_reading = katakana(str(card.get("reading") or ""))
        unanimous_current_reading = bool(
            analyzers_agree
            and (
                is_inflected_surface
                or sudachi_reading == expected_dictionary_reading
            )
        )
        alignment_readings = readings
        if is_inflected_surface and analyzers_agree:
            current = hiragana(str(card.get("reading") or ""))
            current_alternative = next(
                (item for item in readings if item.reading == current), None
            )
            if current_alternative is not None:
                alignment_readings = (ReadingAlternative(
                    reading=current_alternative.reading,
                    entry_id=current_alternative.entry_id,
                    sense_index=current_alternative.sense_index,
                    gloss=current_alternative.gloss,
                    contextual_reading=hiragana(sudachi_reading),
                ),)
        attempts = []
        selected: Optional[Tuple[ReadingAlternative, AlignmentEvidence]] = None
        selected_bounds: Optional[Tuple[int, int]] = None
        selected_source = "hiragana-ctc"
        for attempt_name, padding in (
            ("narrow", self.config.narrow_padding_ms),
            ("expanded", self.config.expanded_padding_ms),
        ):
            working_start = max(0, start_ms - padding)
            working_end = end_ms + padding
            if working_end - working_start > self.config.maximum_working_window_ms:
                break
            wav = cache_directory / "audio" / f"{key}-{attempt_name}.wav"
            _extract_window(video, working_start, working_end, wav)
            orthographic = None
            orthographic_alignment = None
            if self.orthographic_transcriber is not None:
                orthographic = self.orthographic_transcriber.transcribe(wav)
                orthographic_alignment = _orthographic_alignment(card, orthographic)
                orthographic_near_boundary = bool(
                    orthographic_alignment.target_start_ms is None
                    or orthographic_alignment.target_end_ms is None
                    or orthographic_alignment.target_start_ms < self.config.boundary_margin_ms
                    or orthographic_alignment.target_end_ms > (
                        orthographic.duration_ms - self.config.boundary_margin_ms
                    )
                )
                if (
                    unanimous_current_reading
                    and orthographic_alignment.target_covered
                    and orthographic_alignment.sentence_coverage
                    >= self.config.minimum_sentence_coverage
                    and orthographic_alignment.target_confidence
                    >= self.config.minimum_target_confidence
                    and not orthographic_near_boundary
                ):
                    current = hiragana(str(card.get("reading") or ""))
                    current_alternative = next(
                        (item for item in readings if item.reading == current), None
                    )
                    if current_alternative is not None:
                        selected = (current_alternative, orthographic_alignment)
                        selected_source = "orthographic_and_unanimous_reading"
                        sentence_start = orthographic_alignment.sentence_start_ms or 0
                        sentence_end = (
                            orthographic_alignment.sentence_end_ms
                            or orthographic.duration_ms
                        )
                        selected_bounds = (
                            max(0, working_start + sentence_start - self.config.output_margin_ms),
                            working_start + sentence_end + self.config.output_margin_ms,
                        )
                        attempts.append({
                            "name": attempt_name,
                            "working_start_ms": working_start,
                            "working_end_ms": working_end,
                            "orthographic_transcript": orthographic.as_dict(),
                            "orthographic_alignment": orthographic_alignment.as_dict(),
                            "reading_consensus": reading_consensus,
                            "selected_by": "orthographic_and_unanimous_reading",
                            "target_near_boundary": False,
                        })
                        break
                if (
                    unanimous_current_reading
                    and orthographic_alignment.target_covered
                    and orthographic_alignment.sentence_coverage
                    >= self.config.minimum_sentence_coverage
                    and orthographic_alignment.target_confidence
                    >= self.config.minimum_target_confidence
                    and orthographic_near_boundary
                ):
                    attempts.append({
                        "name": attempt_name,
                        "working_start_ms": working_start,
                        "working_end_ms": working_end,
                        "orthographic_transcript": orthographic.as_dict(),
                        "orthographic_alignment": orthographic_alignment.as_dict(),
                        "reading_consensus": reading_consensus,
                        "selected_by": "orthographic_boundary_retry",
                        "target_near_boundary": True,
                        "ambiguous": False,
                    })
                    continue
            transcript = self.transcriber.transcribe(wav)
            alignments = [
                _align_candidate(card, transcript, alternative)
                for alternative in alignment_readings
            ]
            eligible = [
                (alternative, alignment)
                for alternative, alignment in zip(alignment_readings, alignments)
                if alignment.target_covered
                and alignment.sentence_coverage >= self.config.minimum_sentence_coverage
                and alignment.target_confidence >= self.config.minimum_target_confidence
            ]
            eligible.sort(
                key=lambda item: (
                    item[1].sentence_coverage,
                    item[1].target_confidence,
                    len(item[0].reading),
                ),
                reverse=True,
            )
            ambiguous = (
                len(eligible) > 1
                and math.isclose(
                    eligible[0][1].sentence_coverage,
                    eligible[1][1].sentence_coverage,
                    abs_tol=0.02,
                )
                and eligible[0][0].reading != eligible[1][0].reading
            )
            near_boundary = False
            if eligible and not ambiguous:
                evidence = eligible[0][1]
                near_boundary = bool(
                    evidence.target_start_ms is None
                    or evidence.target_end_ms is None
                    or evidence.target_start_ms < self.config.boundary_margin_ms
                    or evidence.target_end_ms > (
                        transcript.duration_ms - self.config.boundary_margin_ms
                    )
                )
            attempts.append({
                "name": attempt_name,
                "working_start_ms": working_start,
                "working_end_ms": working_end,
                "transcript": transcript.as_dict(),
                "orthographic_transcript": (
                    orthographic.as_dict() if orthographic else None
                ),
                "orthographic_alignment": (
                    orthographic_alignment.as_dict()
                    if orthographic_alignment else None
                ),
                "unanimous_current_reading": unanimous_current_reading,
                "alignments": [alignment.as_dict() for alignment in alignments],
                "eligible_readings": [item[0].reading for item in eligible],
                "ambiguous": ambiguous,
                "target_near_boundary": near_boundary,
            })
            if eligible and not ambiguous and not near_boundary:
                selected = eligible[0]
                sentence_start = selected[1].sentence_start_ms or 0
                sentence_end = selected[1].sentence_end_ms or transcript.duration_ms
                selected_bounds = (
                    max(0, working_start + sentence_start - self.config.output_margin_ms),
                    working_start + sentence_end + self.config.output_margin_ms,
                )
                break

        if selected is None or selected_bounds is None:
            reason = "ambiguous_audio_reading" if any(
                attempt["ambiguous"] for attempt in attempts
            ) else "target_absent_or_clipped"
            result = self._rejected(card, reason, attempts)
            return self._store(record_path, result)

        alternative, alignment = selected
        current = hiragana(str(card.get("reading") or ""))
        repaired = alternative.reading != current
        accepted_card = dict(card)
        revalidation = None
        if repaired:
            accepted_card = _repaired_card(card, alternative, {
                "backend": "hiragana-ctc",
                "model": CTC_MODEL_REPO,
                "model_revision": CTC_MODEL_REVISION,
                "alignment": alignment.as_dict(),
            })
            lexical_spans = accepted_card.get("target_lexical_spans") or []
            if lexical_spans:
                lexical_start, lexical_end = map(int, lexical_spans[0])
            else:
                lexical_start = accepted_card.get("target_lexical_start")
                lexical_end = accepted_card.get("target_lexical_end")
            consensus = self.reading_validator.validate(
                str(accepted_card.get("japanese") or ""),
                lexical_start,
                lexical_end,
                str(accepted_card["reading"]),
            )
            revalidation = consensus.as_dict()
            if consensus.status != "agreement":
                result = self._rejected(
                    card, "reading_revalidation_failed", attempts,
                    extra={"reading_revalidation": revalidation},
                )
                return self._store(record_path, result)
            accepted_card["reading_consensus"] = revalidation
            accepted_card["audit_findings"] = [f for f in accepted_card.get("audit_findings", [])
                                                if f.get("code") != "reading_disagreement"]
            accepted_card["audit_criteria"] = [
                {**c, "status": "passed", "detail": "Audio reading repair independently rechecked by reading analyzers"}
                if c.get("code") == "contextual_reading" else dict(c)
                for c in accepted_card.get("audit_criteria", [])]
            # A reading repair changes the card fingerprint. Existing recorded
            # semantic reviews must not be silently reused downstream.
            accepted_card["requires_contextual_revalidation"] = True
            accepted_card["superseded_validation_stages"] = list(
                accepted_card.get("validation_stages") or []
            )
            accepted_card["validation_stages"] = []

        accepted_card["start_ms"], accepted_card["end_ms"] = selected_bounds
        stages = list(accepted_card.get("validation_stages") or [])
        audio_stage = f"audio:{selected_source}"
        if audio_stage not in stages:
            stages.append(audio_stage)
        accepted_card["validation_stages"] = stages
        accepted_card["audio_validation"] = {
            "status": "accepted",
            "repaired": repaired,
            "reading": alternative.reading,
            "alignment": alignment.as_dict(),
            "attempts": len(attempts),
            "selected_attempt": attempts[-1]["name"],
            "original_start_ms": start_ms,
            "original_end_ms": end_ms,
            "selected_start_ms": selected_bounds[0],
            "selected_end_ms": selected_bounds[1],
            "reading_revalidation": revalidation,
            "backend": selected_source,
            "selected_by": selected_source,
            "model": CTC_MODEL_REPO,
            "model_revision": CTC_MODEL_REVISION,
            "orthographic_backend": (
                "mlx-whisper" if self.orthographic_transcriber else None
            ),
            "orthographic_model_revision": (
                WHISPER_MODEL_REVISION if self.orthographic_transcriber else None
            ),
            "criteria": {
                "competing_speech": "passed",
                "target_reading_coverage": "passed",
                "sentence_alignment": "passed",
                "clip_boundaries": "passed",
            },
        }
        result = {
            "status": "accepted",
            "reason": "reading_repaired" if repaired else "supported",
            "card": accepted_card,
            "attempts": attempts,
        }
        return self._store(record_path, result)

    @staticmethod
    def _rejected(
        card: Mapping[str, Any], reason: str, attempts: Sequence[Mapping[str, Any]],
        *, extra: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        value = {
            "status": "rejected",
            "reason": reason,
            "candidate_key": card.get("candidate_key"),
            "learning_unit_key": card.get("learning_unit_key"),
            "japanese": card.get("japanese"),
            "attempts": list(attempts),
        }
        if extra:
            value.update(extra)
        return value

    @staticmethod
    def _store(path: Path, result: Mapping[str, Any]) -> dict:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return dict(result)


def review_audio_cards(
    cards: Sequence[Mapping[str, Any]],
    gate: AudioContentGate,
    cache_directory: Path,
    progress: Optional[Callable[[int, int, Mapping[str, Any]], None]] = None,
) -> dict:
    started = time.perf_counter()
    accepted = []
    rejected = []
    for index, card in enumerate(cards, start=1):
        result = gate.review(card, cache_directory)
        if result["status"] == "accepted":
            accepted.append(result["card"])
        else:
            rejected.append(result)
        if progress is not None:
            progress(index, len(cards), result)
    elapsed = time.perf_counter() - started
    return {
        "schema_version": 1,
        "summary": {
            "input": len(cards),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "repaired": sum(
                bool(card.get("audio_validation", {}).get("repaired"))
                for card in accepted
            ),
            "elapsed_seconds": round(elapsed, 3),
            "cards_per_second": round(len(cards) / elapsed, 3) if elapsed else None,
            "accepted_by": dict(Counter(
                str(card.get("audio_validation", {}).get("selected_by"))
                for card in accepted
            )),
            "rejection_reasons": dict(Counter(
                str(result.get("reason")) for result in rejected
            )),
        },
        "model": {
            "backend": "hybrid-orthographic-plus-hiragana-ctc",
            "repo": CTC_MODEL_REPO,
            "revision": CTC_MODEL_REVISION,
            "checkpoint": CTC_CHECKPOINT,
            "orthographic_repo": WHISPER_MODEL_REPO,
            "orthographic_revision": WHISPER_MODEL_REVISION,
        },
        "accepted": accepted,
        "rejected": rejected,
    }
