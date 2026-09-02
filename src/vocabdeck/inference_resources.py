from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path
from typing import IO, Optional


DEFAULT_MLX_MEMORY_LIMIT_GB = 4.0
HARD_MAX_MLX_MEMORY_LIMIT_GB = 6.0
HARD_MAX_MODEL_ARTIFACT_GB = 3.5
_GIB = 1024**3


class InferenceResourceGuard:
    """Fail closed before an MLX model can consume unified memory."""

    def __init__(
        self,
        *,
        memory_limit_gb: float = DEFAULT_MLX_MEMORY_LIMIT_GB,
        max_model_artifact_gb: float = HARD_MAX_MODEL_ARTIFACT_GB,
        lock_path: Optional[Path] = None,
    ) -> None:
        if not 0 < memory_limit_gb <= HARD_MAX_MLX_MEMORY_LIMIT_GB:
            raise ValueError(
                "MLX memory limit must be greater than zero and no more than "
                f"{HARD_MAX_MLX_MEMORY_LIMIT_GB:g} GiB"
            )
        if not 0 < max_model_artifact_gb <= HARD_MAX_MODEL_ARTIFACT_GB:
            raise ValueError(
                "model artifact limit must be greater than zero and no more "
                f"than {HARD_MAX_MODEL_ARTIFACT_GB:g} GiB"
            )
        self.memory_limit_gb = memory_limit_gb
        self.max_model_artifact_gb = max_model_artifact_gb
        self.lock_path = lock_path or (
            Path(tempfile.gettempdir()) / "vocabdeck-mlx-inference.lock"
        )
        self._lock_file: Optional[IO[str]] = None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            lock_file.close()
            raise RuntimeError(
                "another vocabdeck local-inference process is already running; "
                "refusing to overlap model memory"
            ) from error
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={os.getpid()}\n")
        lock_file.flush()
        self._lock_file = lock_file

    def validate_model_path(self, model_path: Path) -> int:
        unique_files = set()
        total_bytes = 0
        for path in model_path.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in unique_files:
                continue
            unique_files.add(resolved)
            total_bytes += resolved.stat().st_size
        artifact_limit = int(self.max_model_artifact_gb * _GIB)
        if total_bytes > artifact_limit:
            raise RuntimeError(
                f"model artifacts use {total_bytes / _GIB:.2f} GiB, above the "
                f"hard {self.max_model_artifact_gb:g} GiB safety ceiling; "
                "refusing to load the model"
            )
        return total_bytes

    def configure_mlx(self, mx: object) -> None:
        memory_limit = int(self.memory_limit_gb * _GIB)
        mx.set_memory_limit(memory_limit)  # type: ignore[attr-defined]
        cache_limit = min(memory_limit // 8, 512 * 1024**2)
        mx.set_cache_limit(cache_limit)  # type: ignore[attr-defined]

    def release(self, mx: Optional[object] = None) -> None:
        if mx is not None:
            try:
                mx.clear_cache()  # type: ignore[attr-defined]
            except Exception:
                pass
        if self._lock_file is not None:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    def __enter__(self) -> "InferenceResourceGuard":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
