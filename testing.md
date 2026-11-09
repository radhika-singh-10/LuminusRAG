# Testing process

How to test LuminusRAG, from unit tests to model comparisons, and how to
record results in [results.md](results.md). The metrics themselves are
described under "Evaluation" in the [README](README.md).

## 0. Before any run

- Use the project venv: `.venv/bin/python` (MLX runs use `.venv-mlx`, see §6).
- Ollama must be running with `llama3.2:3b` for the intent gate, guard,
  knowledge graph and LLM judge: `curl -s localhost:11434/api/tags`.
- The index must match `data/`: `python main.py ingest`. Compare variants
  only against the same index, embeddings and dataset.
- Results go to `eval/results/<timestamp>/` (`summary.json`,
  `per_question.jsonl`); `bench` also writes `eval/results/experiments-<timestamp>.json`.

## 1. Unit tests (every change)

```bash
python -m pytest tests            # chunking + debounce, guardrails, prompt cache
```

## 2. Core RAG eval (every change to retrieval, prompts or the model)

```bash
python main.py eval --limit 5 -n 1 -k 1     # smoke: first 5 questions, one greedy answer
python main.py eval -n 5 -k 1,3,5           # full: 21 questions, 5 samples each
```

Read accuracy together with pass@k and pass^k (consistency), retrieval
recall and MRR, faithfulness / hallucination, abstention F1 and latency.

## 3. Comparing variants (`bench`)

An experiments file lists variants; lower-case keys are run settings
(`n`, `ks`, `temperature`, `top_k`, `limit`, `dataset`), UPPER_CASE keys
override `rag/config.py`.

| File | Compares |
|---|---|
| `eval/experiments.json` | baseline, TOP_K, MMR, generator models |
| `eval/experiments_graph.json` | vector vs graph vs hybrid retrieval |
| `eval/experiments_extensions.json` | reranker, history-aware follow-ups, LLM judge |
| `eval/experiments_chunking.json` | structure-aware chunking at several TOP_K |
| `eval/experiments_rerank.json` | reranker on/off at TOP_K 2, 3, 8 (main + relational sets) |
| `eval/experiments_messy.json` | reranker on/off at TOP_K 2, 3, 8 on the messy corpus |

```bash
python main.py bench --config eval/experiments_rerank.json
python main.py bench --config eval/experiments.json --only baseline,mmr -v
```

### Testing a retrieval change (for example the reranker)

A ranking change can only change accuracy if it changes **which chunks the
model sees**. If recall@k is already 1.0, the answer chunk is already in the
context and reordering it (higher MRR) will barely move accuracy. So:

1. **Sweep TOP_K.** Run each variant at a small TOP_K (2-3) as well as the
   default (8). At a small TOP_K, ranking decides whether the evidence is in
   the context at all.
2. **Test on a corpus where retrieval is hard.** The 6-file `data/` corpus is
   small enough that 20 rerank candidates cover a large part of it. Use the
   messy corpus (below) before ruling a retrieval change in or out.
3. **Look at per-question results** (`per_question.jsonl`): find which
   questions flipped and whether the evidence chunk entered or left the
   top k.
4. **Mind the sample size** (see §7).

### Messy corpus

`eval/messy/build_corpus.py` generates a synthetic ML-platform wiki
(`eval/messy/corpus/`, 5 files, about 3x the chunks of `data/`) and its
question set `eval/messy_dataset.jsonl` (48 questions, 4 unanswerable). It
is deliberately hard for a bi-encoder: production / staging / retired
configs that differ only in numbers, benchmark reruns, templated
postmortems and changelog entries, meeting notes whose decisions are later
reversed, plus boilerplate and OCR-style line breaks. The script checks that
every evidence string occurs in exactly one section.

It uses its own index, so it never touches `chroma_db/`:

```bash
python eval/messy/build_corpus.py                                   # deterministic (fixed seed)
export DATA_DIR=eval/messy/corpus PERSIST_DIR=eval/messy/chroma_db
python main.py ingest                                               # ~4 min incl. graph extraction
python main.py bench --config eval/experiments_messy.json
unset DATA_DIR PERSIST_DIR
```

## 4. Safety, gating and agent evals (changes to guard, intent, agent)

```bash
python main.py eval-guard        # policy guard on labeled attack / benign questions
python main.py eval-intent       # intent gate
python main.py eval-security     # end-to-end PII + prompt injection (leak rate must stay 0)
python main.py eval-agent --compare
```

## 5. Ingestion evals (changes to chunking, OCR, watcher)

```bash
python main.py eval-chunking     # no overlap, exact partition, code retrieval, debounced sync
python main.py eval-ocr          # CER / WER and retrieval on synthetic scans
```

## 6. Fine-tuned MLX model

See [finetuning.md](finetuning.md) for training. To evaluate an adapter,
use `.venv-mlx` (it needs both `requirements.txt` and `mlx-lm[train]`) in a
session with Metal access:

```bash
export LLM_PROVIDER=mlx
export MLX_MODEL_PATH=finetune/models/qwen2.5-1.5b-instruct
export MLX_ADAPTER_PATH=finetune/adapters/qwen25-1.5b-v1
.venv-mlx/bin/python main.py eval -n 1 -k 1 --limit 5   # smoke
.venv-mlx/bin/python main.py eval -n 1 -k 1             # full set
```

Always compare against the same base model **without** the adapter, with the
same settings (`-n 1 -k 1`, same index), not against a run with a different
model or sampling setup.

## 7. Reading results

- **Sample size:** the main set has 21 questions and the relational and
  follow-up sets 10. One question flipping moves accuracy by about 0.05
  (main) or 0.10 (10-question sets), so a difference of a few points is
  noise. Use `-n 3` or more and prefer the 48-question messy set when a
  decision depends on the difference.
- **Sampled vs greedy:** `-n 1` is greedy and `-n > 1` samples at
  `--temperature`; do not compare one with the other.
- **Retrieval vs generation:** if recall and MRR are unchanged between two
  runs, an accuracy difference comes from generation.

## 8. Recording results

Add a section to [results.md](results.md) with the date, the exact command
or experiments file, the settings that differ from the defaults, a table of
the key metrics, and the conclusion, including caveats about sample size.
When a new run changes an earlier conclusion, update the earlier section
too instead of leaving both versions in place.
