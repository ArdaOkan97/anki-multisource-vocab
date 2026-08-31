import json
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vocabdeck.audio_validation import (
    AudioContentGate,
    AudioGateConfig,
    AlignmentEvidence,
    AudioToken,
    AudioTranscript,
    OrthographicTranscript,
    ReadingAlternative,
    hiragana,
)


class FakeTranscriber:
    def __init__(self, transcripts):
        self.transcripts = list(transcripts)
        self.calls = 0

    def transcribe(self, _audio):
        value = self.transcripts[min(self.calls, len(self.transcripts) - 1)]
        self.calls += 1
        tokens = tuple(
            AudioToken(char, index * 100, (index + 1) * 100, 0.95)
            for index, char in enumerate(value)
        )
        return AudioTranscript(
            value, "", max(1600, len(tokens) * 100), tokens,
            "fake", "fake", "test", "cpu",
        )


class Alternatives:
    def __init__(self, *readings):
        self.readings = readings

    def resolve(self, *_args):
        return tuple(
            ReadingAlternative(reading, 100 + index, index, "I; me")
            for index, reading in enumerate(self.readings)
        )


class ReadingValidator:
    def validate(self, *_args):
        return SimpleNamespace(
            status="agreement", as_dict=lambda: {"status": "agreement"}
        )


class UnanimousReadingValidator:
    def validate(self, *_args):
        return SimpleNamespace(
            status="agreement",
            as_dict=lambda: {
                "status": "agreement",
                "sudachi": "オマエ",
                "openjtalk": "オマエ",
            },
        )


class FakeOrthographicTranscriber:
    def __init__(self, transcripts):
        self.transcripts = list(transcripts)
        self.calls = 0

    def transcribe(self, _audio):
        text, offset = self.transcripts[
            min(self.calls, len(self.transcripts) - 1)
        ]
        self.calls += 1
        tokens = tuple(
            AudioToken(char, offset + index * 100, offset + (index + 1) * 100, 0.95)
            for index, char in enumerate(text)
        )
        return OrthographicTranscript(
            text, 2200, tokens, "fake-whisper", "fake", "test"
        )


def card(tmp_path, **changes):
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"test")
    value = {
        "candidate_key": "old-candidate",
        "learning_unit_key": "old-learning-unit",
        "lexeme_key": "old-lexeme",
        "sense_key": "old-sense",
        "sentence_id": 9,
        "lemma": "私",
        "reading": "ワタクシ",
        "gloss": "I; me",
        "part_of_speech": "代名詞",
        "japanese": "次は私だ！",
        "target_lexical_spans": [[2, 3]],
        "target_lexical_start": 2,
        "target_lexical_end": 3,
        "start_ms": 1000,
        "end_ms": 2500,
        "video_path": str(video),
        "validation_stages": ["llm:contextual"],
    }
    value.update(changes)
    return value


def fake_extract(_video, _start, _end, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0\0" * 1600)
    return destination


def gate(transcripts, alternatives=("わたくし", "わたし"), **config):
    transcriber = FakeTranscriber(transcripts)
    return AudioContentGate(
        transcriber,
        config=AudioGateConfig(**config),
        alternatives=Alternatives(*alternatives),
        reading_validator=ReadingValidator(),
    ), transcriber


def test_competing_speech_fails_without_transcription(tmp_path):
    reviewer, transcriber = gate(["はじまってるのかよこれがしけん"])
    result = reviewer.review(card(
        tmp_path, japanese="≪始まってるのかよ≫ ≪これが試験？≫",
        lemma="始まる", reading="ハジマル", gloss="to begin",
        target_lexical_spans=[[1, 4]],
    ), tmp_path / "cache")
    assert result["status"] == "rejected"
    assert result["reason"] == "competing_speech_marker"
    assert transcriber.calls == 0


@patch("vocabdeck.audio_validation._extract_window", fake_extract)
def test_boundary_retry_expands_and_accepts_target(tmp_path):
    reviewer, transcriber = gate(
        ["だれだおまえ", "あああだれだおまえあああ"],
        alternatives=("おまえ",),
        boundary_margin_ms=500,
    )
    result = reviewer.review(card(
        tmp_path, lemma="お前", reading="オマエ", gloss="you",
        japanese="誰だ お前。", target_lexical_spans=[[3, 5]],
        target_lexical_start=3, target_lexical_end=5,
    ), tmp_path / "cache")
    assert result["status"] == "accepted"
    assert result["card"]["audio_validation"]["selected_attempt"] == "expanded"
    assert transcriber.calls == 2


@patch("vocabdeck.audio_validation._extract_window", fake_extract)
def test_decisive_audio_repairs_watakushi_to_watashi(tmp_path):
    reviewer, _ = gate(["つぎわわたしだ"], boundary_margin_ms=100)
    result = reviewer.review(card(tmp_path), tmp_path / "cache")
    assert result["status"] == "accepted"
    repaired = result["card"]
    assert repaired["reading"] == "ワタシ"
    assert repaired["learning_unit_key"] != "old-learning-unit"
    assert repaired["candidate_key"] != "old-candidate"
    assert repaired["requires_contextual_revalidation"] is True
    assert repaired["validation_stages"] == ["audio:hiragana-ctc"]
    assert repaired["superseded_validation_stages"] == ["llm:contextual"]


@patch("vocabdeck.audio_validation._extract_window", fake_extract)
def test_cached_decision_skips_second_transcription(tmp_path):
    reviewer, transcriber = gate(
        ["つぎわわたしだ"], boundary_margin_ms=100
    )
    cache = tmp_path / "cache"
    candidate = card(tmp_path)
    first = reviewer.review(candidate, cache)
    second = reviewer.review(candidate, cache)
    assert first == second
    assert transcriber.calls == 1


@patch("vocabdeck.audio_validation._extract_window", fake_extract)
def test_hybrid_uses_orthography_only_with_unanimous_current_reading(tmp_path):
    ctc = FakeTranscriber(["ばるだわ"])
    orthographic = FakeOrthographicTranscriber([
        ("誰だお前", 0),
        ("誰だお前港から", 700),
    ])
    reviewer = AudioContentGate(
        ctc,
        alternatives=Alternatives("おまえ", "おまい"),
        reading_validator=UnanimousReadingValidator(),
        orthographic_transcriber=orthographic,
    )
    result = reviewer.review(card(
        tmp_path, lemma="お前", reading="オマエ", gloss="you",
        japanese="誰だ お前。", target_lexical_spans=[[3, 5]],
        target_lexical_start=3, target_lexical_end=5,
    ), tmp_path / "cache")
    assert result["status"] == "accepted"
    assert result["card"]["audio_validation"]["selected_attempt"] == "expanded"
    assert result["card"]["audio_validation"]["selected_by"] == (
        "orthographic_and_unanimous_reading"
    )
    assert ctc.calls == 0
    assert orthographic.calls == 2


@patch("vocabdeck.audio_validation._extract_window", fake_extract)
def test_equally_supported_readings_fail_closed(tmp_path):
    reviewer, _ = gate(
        ["つぎわわたしだ"], boundary_margin_ms=100
    )

    def evidence(_card, _transcript, alternative):
        return AlignmentEvidence(
            reading=alternative.reading,
            sentence_coverage=0.9,
            target_covered=True,
            target_confidence=0.9,
            target_start_ms=300,
            target_end_ms=600,
            sentence_start_ms=200,
            sentence_end_ms=800,
            expected_kana="つぎわ" + alternative.reading + "だ",
        )

    with patch("vocabdeck.audio_validation._align_candidate", evidence):
        result = reviewer.review(card(tmp_path), tmp_path / "cache")
    assert result["status"] == "rejected"
    assert result["reason"] == "ambiguous_audio_reading"
