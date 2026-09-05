# English definition embedding alternatives (2026-09-05)

User-approved experiment in VOCAB-2.5.6. Four pinned models embedded only the
English definitions, not Japanese words or sentences. This does not select the
meaning used in an occurrence and does not authorize dictionary-sense merging.

## Models and input conventions

- Existing model: [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small).
  Both sides use `query: `, its documented convention for symmetric semantic
  similarity. This is the same model as production, **not** a replay of the
  production query/passage scoring operation. Its production cache is untouched.
- English [all-mpnet-base-v2](https://huggingface.co/sentence-transformers/all-mpnet-base-v2),
  a sentence-similarity model; plain definitions, no prefix.
- English [BGE-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5) and
  [BGE-large-en-v1.5](https://huggingface.co/BAAI/bge-large-en-v1.5), plain definitions
  as recommended for non-retrieval tasks. The larger checkpoint is a capacity
  comparison, not a presumption of better accuracy on dictionary equivalence.

The benchmark pins revisions in `src/vocabdeck/embedding_pair_probe.py`.
Only required safetensors/tokenizer/pooling files are downloaded; duplicate ONNX,
OpenVINO and PyTorch checkpoint formats are excluded. New root weight downloads
were approximately 438 MB, 438 MB and 1.341 GB respectively. No quantization or
remote model code is used.

## Cohort and safety

20 pairs / 34 distinct definition strings: the six original dictionary-sense
pairs, two identical-definition controls, and 12 transparent assistant-authored
diagnostics (four paraphrases, six related-but-distinct pairs, two unrelated
pairs). These categories are **provisional diagnostic intent, not independently
reviewed gold**. No threshold was tuned or adopted. All pair-set hashes matched
across models and the outputs retain the exact strings, scores and provenance.

Each model ran in a separate sequential CPU process, batch size four, with two
PyTorch compute threads. The existing global inference lock prevents overlap
with the local LLM runs. A 50 ms RSS watchdog aborts above 4 GiB and a synchronous
check rejects an over-budget result. This is a monitored process ceiling, not
an OS-enforced instantaneous allocation cap; it does not measure whole-system
memory. No accelerator memory was used. All processes exited successfully.

| Model | Load + embed 34 strings | Measured peak process RSS |
| --- | ---: | ---: |
| E5-small | 1.88 s | 1.006 GiB |
| MPNet-base | 0.67 s | 0.820 GiB |
| BGE-base | 1.15 s | 0.817 GiB |
| BGE-large | 3.74 s | 1.621 GiB |

Load/encode timings exclude download and library import time. Download/setup
times were 0.52, 13.30, 12.85 and 31.43 seconds. These are tiny first-run
diagnostics, not steady-state throughput measurements. Normalized vectors are
cached with model revision, prefix, input text, length limit and dtype identity.
No input exceeded the 128-token cap; oversized inputs are rejected, not silently
truncated. Cosine is symmetric and both identical controls scored 1.0 for every
model. Existing production similarity thresholds must not be copied between
models: their score distributions differ substantially.

## Cosine results (not probabilities)

| Definition pair | E5-small | MPNet | BGE-base | BGE-large |
| --- | ---: | ---: | ---: | ---: |
| 何: what / what?; huh? | .891 | .338 | .758 | .744 |
| あれ: that; that thing / huh?; eh?; what? | .896 | .275 | .686 | .702 |
| 分かる: understand; comprehend; grasp / become clear; be known; be discovered | .929 | .615 | .753 | .725 |
| こっち: this way; this direction / here | .838 | .187 | .734 | .675 |
| どっち: which way; which direction; where / which one | .849 | .322 | .680 | .706 |
| くれる: do for one; take the trouble to do / give; let one have | .921 | .394 | .715 | .716 |
| begin; start / commence | .922 | .648 | .882 | .888 |
| buy / purchase | .986 | .917 | .930 | .962 |
| understand; comprehend / grasp the meaning | .870 | .737 | .794 | .865 |
| allow / permit | .927 | .821 | .873 | .926 |
| give / receive | .952 | .668 | .786 | .843 |
| lend / borrow | .896 | .797 | .939 | .956 |
| increase / decrease | .927 | .694 | .641 | .661 |
| permitted / not permitted | .914 | .701 | .839 | .828 |
| before / after | .904 | .693 | .723 | .778 |
| enter / leave | .905 | .577 | .735 | .777 |
| rabbit; hare / understand; comprehend | .875 | .186 | .478 | .557 |
| that; that thing / swim | .805 | .156 | .515 | .565 |

English alternatives separate several obvious dissimilar pairs more clearly
from paraphrases, but **all four have overlapping paraphrase and related-distinct
score ranges**. For example BGE-large scores lend/borrow (.956) above allow/permit
(.926) and begin/commence (.888). MPNet also scores lend/borrow (.797) above
begin/commence (.648). E5 ranks give/receive (.952) above begin/commence (.922).
There is no threshold that separates all of these diagnostics perfectly.

The result supports embeddings as a cheap candidate-ranking signal, not a
standalone equivalence proof. MPNet is a useful lightweight English comparator
for a larger independently labeled study, but this hand-selected sample cannot
establish a winner or a production precision target. The distinct dictionary
meanings may also have been assigned incorrectly in the original sentences;
this experiment cannot repair that contextual-selection error.

## Reproduce

Use the previously generated source queue from `semantic-repair.md`, then run
this command once per model, waiting for process exit before the next:

```console
TOKENIZERS_PARALLELISM=false HF_HUB_DISABLE_XET=1 \
.venv/bin/python -m vocabdeck.embedding_pair_probe \
  --dataset .vocabdeck/benchmarks/semantic-repair-v1-queue.json \
  --model mpnet --output .vocabdeck/benchmarks/embedding-pairs-mpnet.json
```

Model keys are `e5`, `mpnet`, `bge-base`, `bge-large`. The four local
`embedding-pairs-*.json` reports contain scores and resource measurements;
`embedding-vectors-*.json` holds cached vectors. Metadata resolution uses the
public Hugging Face Hub even when cached weights exist. Nine added tests cover
cosine/identity/symmetry, invalid vectors, provisional provenance, model pinning
and the RSS configuration ceiling. Full suite: 248 tests passed.

Production, the frozen baseline, and all merge thresholds remain unchanged.
Independent annotation and held-out evaluation in VOCAB-2.5.6 remain pending.
