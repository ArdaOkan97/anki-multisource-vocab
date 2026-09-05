"""Sequential offline inference phases. Parent holds no model weights."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from .semantic_benchmark import _write


def run_phase(request, *, memory_limit_gb=4.0, timeout_seconds=900):
    if not 0 < memory_limit_gb <= 4:
        raise ValueError("isolated phase memory ceiling must be >0 and <=4 GiB")
    if not 0 < timeout_seconds <= 3600:
        raise ValueError("invalid isolated phase timeout")
    with tempfile.TemporaryDirectory(prefix="vocabdeck-phase-") as directory:
        source, output = Path(directory) / "input.json", Path(directory) / "output.json"
        _write(source, {**request, "memory_limit_gb": memory_limit_gb})
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "2"}
        result = subprocess.run([sys.executable, "-m", "vocabdeck.isolated_inference",
                                 "--input", str(source), "--output", str(output)],
                                env=env, capture_output=True, text=True, timeout=timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(f"isolated {request['kind']} phase failed ({result.returncode}): {result.stderr[-2000:]}")
        payload = json.loads(output.read_text())
        payload["runtime"]["process_exit_verified"] = True
        return payload


class IsolatedDatasetReviewer:
    isolated_phases = True

    def __init__(self, model, revision, memory_limit_gb=4.0):
        self.model_id, self.model_revision = model, revision
        self.memory_limit_gb = memory_limit_gb
        self.model_name = f"{model}@{revision}"

    def review_dataset(self, dataset, prompt_version):
        result = run_phase({"kind": "semantic", "dataset": dataset,
                            "model": self.model_id, "revision": self.model_revision,
                            "prompt_version": prompt_version}, memory_limit_gb=self.memory_limit_gb)
        report = result["predictions"]
        report["runtime"] = result["runtime"]
        return report

    def close(self):
        pass  # No model is resident in this parent.


class IsolatedAudioTranscriber:
    def __init__(self, kind, memory_limit_gb=4.0):
        if kind not in {"ctc", "whisper"}:
            raise ValueError("invalid audio backend")
        self.kind, self.memory_limit_gb = kind, memory_limit_gb

    def transcribe(self, audio):
        from .audio_validation import AudioToken, AudioTranscript, OrthographicTranscript
        result = run_phase({"kind": self.kind, "audio": str(Path(audio).resolve())},
                           memory_limit_gb=self.memory_limit_gb)
        data = result["transcript"]
        data["tokens"] = tuple(AudioToken(**token) for token in data["tokens"])
        data["runtime"] = result["runtime"]
        return (AudioTranscript if self.kind == "ctc" else OrthographicTranscript)(**data)


def make_audio_gate(memory_limit_gb=4.0):
    if not 0 < memory_limit_gb <= 4:
        raise ValueError("audio phase memory ceiling must be >0 and <=4 GiB")
    from .audio_validation import AudioContentGate
    gate = AudioContentGate(IsolatedAudioTranscriber("ctc", memory_limit_gb),
                            orthographic_transcriber=IsolatedAudioTranscriber("whisper", memory_limit_gb))
    gate.resource_policy = {"isolation": "one_backend_per_child_process", "offline": True,
                            "rss_limit_gib": memory_limit_gb, "ctc_device": "cpu",
                            "shared_inference_lock": True, "process_exit_before_next_phase": True}
    return gate


def worker(request):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from .embedding_pair_probe import peak_rss_bytes, start_rss_watchdog
    from .inference_resources import InferenceResourceGuard
    limit = float(request["memory_limit_gb"])
    if not 0 < limit <= 4:
        raise ValueError("invalid worker memory ceiling")
    started, stop = time.perf_counter(), threading.Event()
    watcher = start_rss_watchdog(limit * 1024**3, stop)
    try:
        if request["kind"] == "probe":
            with InferenceResourceGuard(memory_limit_gb=limit):
                result = {"probe": "no_model_loaded"}
        elif request["kind"] == "semantic":
            from .constrained_review import MLXLabelReviewer, run_constrained_dataset
            reviewer = MLXLabelReviewer(request["model"], revision=request["revision"], memory_limit_gb=limit)
            try:
                result = {"predictions": run_constrained_dataset(
                    request["dataset"], reviewer, prompt_version=request["prompt_version"])}
            finally:
                reviewer.close()
        else:
            from .audio_validation import (
                HiraganaCTCTranscriber, MLXWhisperTranscriber, CTC_MODEL_REPO,
                CTC_MODEL_REVISION, CTC_CHECKPOINT, WHISPER_MODEL_REPO, WHISPER_MODEL_REVISION)
            from huggingface_hub import hf_hub_download, snapshot_download
            guard = InferenceResourceGuard(memory_limit_gb=limit)
            with guard:
                if request["kind"] == "ctc":
                    checkpoint = hf_hub_download(CTC_MODEL_REPO, CTC_CHECKPOINT,
                                                 revision=CTC_MODEL_REVISION, local_files_only=True)
                    guard.validate_model_path(Path(checkpoint).parent)
                    import torch
                    torch.set_num_threads(2)
                    torch.set_num_interop_threads(1)
                    transcriber = HiraganaCTCTranscriber(device="cpu")
                elif request["kind"] == "whisper":
                    model_path = snapshot_download(
                        WHISPER_MODEL_REPO, revision=WHISPER_MODEL_REVISION,
                        local_files_only=True, allow_patterns=["*.npz", "*.safetensors", "*.json"])
                    guard.validate_model_path(Path(model_path))
                    import mlx.core as mx
                    guard.configure_mlx(mx)
                    transcriber = MLXWhisperTranscriber()
                    transcriber._model_path = model_path
                else:
                    raise ValueError("unknown worker phase")
                result = {"transcript": transcriber.transcribe(Path(request["audio"])).as_dict()}
                # The subprocess exits before another phase is started. Never
                # reuse a Whisper/CTC runtime in the semantic parent.
                del transcriber
        if peak_rss_bytes() > limit * 1024**3:
            raise MemoryError("isolated phase exceeded monitored RSS ceiling")
        result["runtime"] = {"kind": request["kind"], "pid": os.getpid(), "offline": True,
                             "rss_limit_gib": limit, "peak_process_rss_gib": peak_rss_bytes()/1024**3,
                             "seconds": time.perf_counter()-started, "shared_inference_lock": True}
        return result
    finally:
        stop.set()
        watcher.join(timeout=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    _write(args.output, worker(json.loads(Path(args.input).read_text())))


if __name__ == "__main__":
    main()
