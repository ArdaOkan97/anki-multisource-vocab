from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str


_TIMING = re.compile(
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2}):(?P<ss>\d{2})[,.](?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2})[,.](?P<ems>\d{3})"
)
_HTML = re.compile(r"<[^>]+>")
_ASS_OVERRIDE = re.compile(r"\{\\[^}]+\}")
_SPEAKER = re.compile(r"^(?:[（(][^）)]{1,24}[）)]\s*)+")
_ENGLISH_TERMINAL = re.compile(r'[.!?]["”’)]*$')
_CONTINUATION_ENDINGS = (",", ";", ":", "—", "-", "…")


def _millis(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return (((int(hours) * 60) + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def clean_text(value: str) -> str:
    value = _HTML.sub("", value)
    value = _ASS_OVERRIDE.sub("", value)
    value = " ".join(value.replace("\\N", " ").split())
    value = value.replace("((", "").replace("))", "")
    return _SPEAKER.sub("", value).strip()


def parse_srt_text(raw: str) -> List[Cue]:
    raw = raw.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", raw.strip())
    cues: List[Cue] = []
    for fallback_index, block in enumerate(blocks, start=1):
        lines = [line for line in block.split("\n") if line.strip()]
        timing_pos = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_pos is None:
            continue
        match = _TIMING.search(lines[timing_pos])
        if not match:
            continue
        try:
            index = int(lines[0].strip()) if timing_pos else fallback_index
        except ValueError:
            index = fallback_index
        data = match.groupdict()
        text = clean_text(" ".join(lines[timing_pos + 1 :]))
        if text:
            cues.append(
                Cue(
                    index=index,
                    start_ms=_millis(data["sh"], data["sm"], data["ss"], data["sms"]),
                    end_ms=_millis(data["eh"], data["em"], data["es"], data["ems"]),
                    text=text,
                )
            )
    return cues


def read_srt(path: Path) -> List[Cue]:
    return parse_srt_text(path.read_text(encoding="utf-8-sig"))


def merge_continuations(cues: Iterable[Cue], max_gap_ms: int = 500) -> List[Cue]:
    merged: List[Cue] = []
    pending: Optional[Cue] = None
    for cue in cues:
        if pending is not None:
            if cue.start_ms - pending.end_ms <= max_gap_ms:
                cue = Cue(
                    pending.index,
                    pending.start_ms,
                    cue.end_ms,
                    f"{pending.text.rstrip('→').rstrip()} {cue.text}".strip(),
                )
            else:
                merged.append(pending)
        if cue.text.rstrip().endswith("→"):
            pending = cue
        else:
            merged.append(cue)
            pending = None
    if pending is not None:
        merged.append(pending)
    return merged


def _is_continuation(previous: Cue, following: Cue, max_gap_ms: int = 150) -> bool:
    if following.start_ms - previous.end_ms > max_gap_ms:
        return False
    left = previous.text.rstrip()
    right = following.text.lstrip()
    return left.endswith(_CONTINUATION_ENDINGS) or (
        right[:1].islower() and not _ENGLISH_TERMINAL.search(left)
    )


def _translation_groups(candidates: List[Cue]) -> List[List[Cue]]:
    groups: List[List[Cue]] = []
    for candidate in candidates:
        if groups and _is_continuation(groups[-1][-1], candidate):
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    return groups


def align_translation(cue: Cue, translations: Iterable[Cue]) -> Optional[str]:
    candidates = sorted(translations, key=lambda item: (item.start_ms, item.end_ms))
    japanese_duration = max(1, cue.end_ms - cue.start_ms)
    scored = []
    for group in _translation_groups(candidates):
        overlap = sum(
            max(0, min(cue.end_ms, item.end_ms) - max(cue.start_ms, item.start_ms))
            for item in group
        )
        if overlap <= 0:
            continue
        group_duration = max(1, group[-1].end_ms - group[0].start_ms)
        midpoint_distance = abs(
            (cue.start_ms + cue.end_ms)
            - (group[0].start_ms + group[-1].end_ms)
        )
        scored.append(
            {
                "group": group,
                "overlap": overlap,
                "group_coverage": overlap / group_duration,
                "japanese_coverage": overlap / japanese_duration,
                "midpoint_distance": midpoint_distance,
            }
        )
    if not scored:
        return None

    # Keep translations substantially covered by the Japanese interval. Weak
    # boundary overlaps usually belong to the previous or following utterance.
    selected = [
        item for item in scored
        if item["group_coverage"] >= 0.5 or item["japanese_coverage"] >= 0.35
    ]
    if not selected:
        selected = [
            max(scored, key=lambda item: (item["overlap"], -item["midpoint_distance"]))
        ]

    texts = []
    for item in selected:
        for candidate in item["group"]:
            if candidate.text not in texts:
                texts.append(candidate.text)
    return " ".join(texts)
