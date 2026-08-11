from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Sequence


EPISODE_FILE = re.compile(
    r"^(?P<prefix>.+) - (?P<episode>\d+) \[[^]]+\]\.(?P<extension>mkv|srt)$",
    re.IGNORECASE,
)


def discover_episode_files(directory: Path) -> Dict[int, Dict[str, Path]]:
    episodes: Dict[int, Dict[str, Path]] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = EPISODE_FILE.match(path.name)
        if match is None:
            continue
        episode = int(match.group("episode"))
        extension = match.group("extension").lower()
        if extension in episodes.setdefault(episode, {}):
            raise ValueError(f"Multiple {extension} files found for episode {episode}")
        episodes[episode][extension] = path.resolve()
    return episodes


def build_manifest(
    directory: Path,
    output: Path,
    *,
    series: str,
    season: int,
    episodes: Sequence[int],
    english_track: int,
) -> Path:
    directory = directory.expanduser().resolve()
    discovered = discover_episode_files(directory)
    items = []
    for episode in episodes:
        files = discovered.get(int(episode), {})
        missing = [extension for extension in ("mkv", "srt") if extension not in files]
        if missing:
            raise FileNotFoundError(
                f"Episode {episode} is missing: {', '.join(missing)}"
            )
        items.append({
            "episode": int(episode),
            "video": str(files["mkv"]),
            "japanese": {"srt": str(files["srt"])},
            "english": {"track": int(english_track)},
        })
    document = {"series": series, "season": int(season), "episodes": items}
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output
