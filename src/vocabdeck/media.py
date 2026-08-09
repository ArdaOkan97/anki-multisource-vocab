from __future__ import annotations

import json
import subprocess
import hashlib
from pathlib import Path
from typing import Any, Dict, List


def probe_subtitle_streams(video: Path) -> List[Dict[str, Any]]:
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(process.stdout).get("streams", [])


def extract_subtitle_stream(video: Path, stream_index: int, destination: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-map", f"0:{stream_index}", str(destination)],
        check=True,
    )


def render_card_media(
    video: Path, start_ms: int, end_ms: int, output_directory: Path, identity: str
) -> Dict[str, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(
        f"{video.resolve()}:{start_ms}:{end_ms}:{identity}".encode("utf-8")
    ).hexdigest()[:20]
    audio = output_directory / f"msv_{digest}.mp3"
    image = output_directory / f"msv_{digest}.jpg"
    start = max(0, start_ms - 200) / 1000
    duration = max(0.4, (end_ms - start_ms + 400) / 1000)
    midpoint = max(0, (start_ms + end_ms) / 2000)
    if not audio.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(video),
                "-t", f"{duration:.3f}", "-vn", "-codec:a", "libmp3lame", "-q:a", "4", str(audio),
            ],
            check=True,
        )
    if not image.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-ss", f"{midpoint:.3f}", "-i", str(video),
                "-frames:v", "1", "-q:v", "3", str(image),
            ],
            check=True,
        )
    return {"audio": audio, "image": image}
