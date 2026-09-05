"""CPU-only, RSS-monitored diagnostic of English definition embeddings."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import resource
import sys
import threading
import time

from .dictionary_pair_probe import build_pairs
from .inference_resources import InferenceResourceGuard
from .semantic_benchmark import digest, _write

MODELS = {
    "e5": ("intfloat/multilingual-e5-small", "614241f622f53c4eeff9890bdc4f31cfecc418b3", "query: "),
    "mpnet": ("sentence-transformers/all-mpnet-base-v2", "e8c3b32edf5434bc2275fc9bab85f82640a19130", ""),
    "bge-base": ("BAAI/bge-base-en-v1.5", "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a", ""),
    "bge-large": ("BAAI/bge-large-en-v1.5", "d4aa6901d3a41ba39fb536a557fa166f842b0e09", ""),
}

# Diagnostic examples, explicitly not human-reviewed benchmark gold.
DIAGNOSTICS = [
    ("paraphrase", "to begin; to start", "to commence"),
    ("paraphrase", "to buy", "to purchase"),
    ("paraphrase", "to understand; to comprehend", "to grasp the meaning"),
    ("paraphrase", "to allow", "to permit"),
    ("related_distinct", "to give", "to receive"),
    ("related_distinct", "to lend", "to borrow"),
    ("related_distinct", "to increase", "to decrease"),
    ("related_distinct", "permitted", "not permitted"),
    ("related_distinct", "before", "after"),
    ("related_distinct", "to enter", "to leave"),
    ("unrelated", "a rabbit; a hare", "to understand; to comprehend"),
    ("unrelated", "that; that thing", "to swim"),
]


def make_pairs(dataset):
    pairs = [{"word": p["word"], "definitions": [m["gloss"] for m in p["meanings"]],
              "kind": p["kind"], "source_case_id": p["case_id"], "gold": None}
             for p in build_pairs(dataset)]
    pairs += [{"word": None, "definitions": [left, right], "kind": "assistant_diagnostic",
               "provisional_category": category, "gold": None}
              for category, left, right in DIAGNOSTICS]
    for pair in pairs:
        pair["case_id"] = digest(pair)[:24]
    return pairs


def cosine(left, right):
    if len(left) != len(right) or not left or not all(math.isfinite(x) for x in [*left, *right]):
        raise ValueError("invalid embedding vectors")
    denominator = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    if denominator == 0:
        raise ValueError("zero embedding vector")
    return max(-1.0, min(1.0, sum(a*b for a, b in zip(left, right)) / denominator))


def peak_rss_bytes():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)


def start_rss_watchdog(limit_bytes, stop):
    def watch():
        while not stop.wait(0.05):
            if peak_rss_bytes() > limit_bytes:
                print("Aborting embedding probe: monitored process RSS exceeded ceiling", file=sys.stderr, flush=True)
                # Exit releases the OS file lock, even if model loading is in C.
                os._exit(75)
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


def run(model_key, dataset, output, rss_limit_gib=4.0):
    if not 0 < rss_limit_gib <= 4.0:
        raise ValueError("RSS ceiling must be >0 and <=4 GiB")
    pairs = make_pairs(dataset)
    texts = sorted({text for pair in pairs for text in pair["definitions"]})
    model_id, revision, prefix = MODELS[model_key]
    cache_key = digest({"model": model_id, "revision": revision, "prefix": prefix,
                        "texts": texts, "max_length": 128, "dtype": "float32"})
    cache_path = Path(output).parent / f"embedding-vectors-{cache_key}.json"
    stop = threading.Event()
    guard = InferenceResourceGuard()
    started = time.perf_counter()
    with guard:
        watcher = start_rss_watchdog(rss_limit_gib * 1024**3, stop)
        try:
            from huggingface_hub import HfApi, snapshot_download
            load_started = time.perf_counter()
            # Only download the root safetensors and tokenizer/pooling configs;
            # exclude duplicate PyTorch, ONNX and OpenVINO weights.
            info = HfApi().model_info(model_id, revision=revision, files_metadata=True)
            files = [s for s in info.siblings if (
                s.rfilename == "model.safetensors" or
                (s.rfilename.endswith(".json") and not s.rfilename.startswith(("onnx/", "openvino/"))) or
                s.rfilename in ("vocab.txt", "tokenizer.model", "sentencepiece.bpe.model")
            )]
            if any(s.size is None for s in files) or sum(s.size for s in files) > 2 * 1024**3:
                raise ValueError("missing file sizes or embedding artifact exceeds 2 GiB")
            model_path = snapshot_download(model_id, revision=revision,
                                           allow_patterns=[s.rfilename for s in files], max_workers=1)
            guard.validate_model_path(Path(model_path))
            download_seconds = time.perf_counter() - load_started
            encode_seconds = 0.0
            cache_hit = cache_path.exists()
            if cache_hit:
                cached = json.loads(cache_path.read_text())
                if cached["cache_key"] != cache_key or set(cached["vectors"]) != set(texts):
                    raise ValueError("embedding cache identity mismatch")
                vectors = cached["vectors"]
            else:
                import torch
                torch.set_num_threads(2)
                torch.set_num_interop_threads(1)
                from sentence_transformers import SentenceTransformer
                encode_started = time.perf_counter()
                model = SentenceTransformer(model_path, device="cpu", local_files_only=True,
                                            trust_remote_code=False)
                model.max_seq_length = 128
                inputs = [prefix + text for text in texts]
                if any(len(model.tokenizer.encode(text)) > 128 for text in inputs):
                    raise ValueError("definition would be truncated")
                encoded = model.encode(inputs, batch_size=4, normalize_embeddings=True,
                                       show_progress_bar=False)
                vectors = {text: vector.tolist() for text, vector in zip(texts, encoded)}
                encode_seconds = time.perf_counter() - encode_started
                _write(cache_path, {"cache_key": cache_key, "vectors": vectors})
            records = [{**pair, "cosine": cosine(*(vectors[t] for t in pair["definitions"]))}
                       for pair in pairs]
            if peak_rss_bytes() > rss_limit_gib * 1024**3:
                raise MemoryError("embedding probe exceeded its monitored RSS ceiling")
            report = {"schema_version": 1, "model": model_id, "revision": revision,
                      "input_prefix_both_sides": prefix, "pairs_hash": digest(pairs),
                      "records": records, "threshold_adopted": None, "gold_scored": 0,
                      "runtime": {"device": "cpu", "batch_size": 4, "cpu_threads": 2,
                                  "rss_limit_gib": rss_limit_gib, "cache_hit": cache_hit,
                                  "unique_definitions": len(texts), "download_seconds": download_seconds,
                                  "load_and_encode_seconds": encode_seconds,
                                  "elapsed_seconds": time.perf_counter() - started,
                                  "peak_process_rss_gib": peak_rss_bytes() / 1024**3}}
        finally:
            stop.set()
            watcher.join(timeout=1)
    report["runtime"]["cleanup_completed"] = True
    _write(output, report)
    print(json.dumps({"model": model_key, **report["runtime"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.model, json.loads(Path(args.dataset).read_text()), args.output)


if __name__ == "__main__":
    main()
