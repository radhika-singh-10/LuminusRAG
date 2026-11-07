# Evaluation Results

Run on 2026-11-07 with `python main.py eval -n 5 -k 1,3,5`, `python main.py eval-intent`, and `python main.py bench`.

## Setup

| Setting | Value |
|---|---|
| Questions | 21 (17 answerable, 4 unanswerable) |
| Samples per question | 5 |
| Temperature | 0.7 |
| Generator LLM | `Qwen/Qwen2.5-1.5B-Instruct` (local) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Retrieval | top 4, similarity |
| Truthfulness (NLI) model | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` |
| Runtime | 86.8 s |

The RAG eval calls retrieval and generation directly, so it measures the pipeline without the intent gate or web fallback. The knowledge base includes the files in `data/` plus any web passages saved by earlier questions.

## Key findings

- **Accuracy is 0.79 overall, but answers aren't consistent.** pass@5 is 0.95
  (some sampled answer is usually right), while pass^5 is 0.52 (all five right
  only about half the time).
- **Greedy decoding beats sampling** for this model: 0.81 accuracy with one
  deterministic answer, versus 0.77 for the sampled baseline in the same bench.
- **Answers are grounded:** 90% of checkable sentences are supported by the
  retrieved text, and contradictions are rare (0.6%).
- **MMR retrieval hurts here:** accuracy drops to 0.60 and hallucination rises to
  0.31, because it trades the best-matching chunks for diversity in a small store.
- **Citations are missing:** the local model never writes `[1]`-style citations
  (0%). Sources are still shown, because they come from retrieval.
- **Retrieval recall is perfect, precision is low (0.27):** with a small store,
  4 chunks usually include the answer plus unrelated text.
- **The intent gate scored 49/49**, including action requests in Spanish,
  French and Hindi.

## Generation

| Metric | Score |
|---|---|
| Accuracy (all questions) | 0.790 |
| Accuracy (answerable only) | 0.824 |
| pass@1 | 0.790 |
| pass@3 | 0.929 |
| pass@5 | 0.952 |
| pass^1 | 0.790 |
| pass^3 | 0.614 |
| pass^5 | 0.524 |

pass@k is the chance that at least one of k sampled answers is correct; pass^k is the chance that all k are. The gap between pass@5 and pass^5 shows how consistent the model is.

## Retrieval

| Metric | Score |
|---|---|
| precision at k | 0.265 |
| recall at k | 1.000 |
| hit rate | 1.000 |
| mrr | 0.789 |
| ndcg | 0.838 |

A chunk counts as relevant if it contains one of the question's `evidence` strings.

## Answer quality

| Metric | Score |
|---|---|
| token precision | 0.577 |
| token recall | 0.826 |
| token f1 | 0.633 |
| citation rate | 0.000 |
| citation validity | 0.000 |

Token scores compare the answer's words with the reference answer.

## Truthfulness

| Metric | Score |
|---|---|
| faithfulness | 0.901 |
| contradiction rate | 0.006 |
| reference entailment | 0.797 |
| hallucination rate | 0.168 |
| claim coverage | 0.953 |

Faithfulness is the share of answer sentences entailed by the retrieved text, checked by the NLI model. `claim_coverage` is the share of answers long enough to check.

## Abstention ("I don't know")

| Metric | Score |
|---|---|
| precision | 0.929 |
| recall | 0.650 |
| f1 | 0.765 |

Positive class = questions the documents can't answer.

## Per question

| Question | Answerable | Correct (of 5) | pass^5 | Faithfulness |
|---|---|---|---|---|
| What are the pipeline stages of RAG? | yes | 5 | 1.000 | 0.80 |
| How many dimensions does the all-MiniLM-L6-v2 embedding model produce? | yes | 5 | 1.000 | 1.00 |
| What example chunk size and overlap are given for splitting documents? | yes | 1 | 0.000 | 0.50 |
| Which database is mentioned for persisting vectors? | yes | 5 | 1.000 | 1.00 |
| What does RAG combine? | yes | 5 | 1.000 | 1.00 |
| What can happen if chunks have no overlap? | yes | 3 | 0.000 | 1.00 |
| Why might a model hallucinate in a RAG system? | yes | 4 | 0.000 | 0.50 |
| Which reranker model does the system use? | no | 3 | 0.000 | n/a |
| How much does it cost per month to run this RAG system in production? | no | 4 | 0.000 | n/a |
| What is the range of cosine similarity? | yes | 5 | 1.000 | 1.00 |
| How many bytes does a 384-dimensional float32 vector need? | yes | 0 | 0.000 | 1.00 |
| What must you do if you change the embedding model? | yes | 5 | 1.000 | 1.00 |
| What does HNSW stand for? | yes | 5 | 1.000 | 1.00 |
| What is the main cost of an HNSW index? | yes | 5 | 1.000 | 1.00 |
| What happens if you re-ingest a file without stable ids? | yes | 3 | 0.000 | 0.60 |
| In what order does recursive chunking try separators? | yes | 5 | 1.000 | 1.00 |
| How does the parent document pattern work? | yes | 5 | 1.000 | 1.00 |
| Can an answer be faithful and still wrong? | yes | 5 | 1.000 | 1.00 |
| How do pass@k and pass^k change as k grows? | yes | 4 | 0.000 | 1.00 |
| Which GPU model is recommended for serving this vector database? | no | 4 | 0.000 | n/a |
| Who invented the HNSW algorithm and in what year? | no | 2 | 0.000 | n/a |

## Variant comparison (`bench`)

| Variant | Accuracy | pass@k | pass^k | Retrieval P | Retrieval R | MRR | Token F1 | Faithfulness | Hallucination | Abstention F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| greedy | 0.810 | 0.810 | 0.810 | 0.265 | 1.000 | 0.789 | 0.648 | 0.875 | 0.100 | 0.889 |
| baseline | 0.771 | 0.952 | 0.524 | 0.265 | 1.000 | 0.789 | 0.614 | 0.916 | 0.130 | 0.842 |
| top2 | 0.676 | 0.810 | 0.381 | 0.412 | 0.824 | 0.735 | 0.554 | 0.838 | 0.189 | 0.857 |
| mmr | 0.600 | 0.762 | 0.476 | 0.191 | 0.765 | 0.706 | 0.543 | 0.753 | 0.305 | 0.632 |

- **greedy**: 1 deterministic answer per question (temperature 0), so pass@k = pass^k = accuracy.
- **baseline**: 5 sampled answers, top 4 chunks.
- **top2**: baseline with 2 chunks retrieved.
- **mmr**: baseline with maximal-marginal-relevance retrieval.

## Intent gate (`eval-intent`)

```text
Intent gate (llama3.2:3b): 49 queries, 0 errors
  accuracy           1.000
  precision          1.000
  recall             1.000
  f1                 1.000
  false allowed      0
  false blocked      0
  secs per query     0.13
variant  accuracy   pass@1   pass@k   pass^k    ret_P    ret_R      MRR   tok_F1 faithful   halluc  abst_F1     secs
```

The positive class is "allowed" (an AI question). The set includes off-topic questions, prompt-injection attempts, and action requests in Spanish, French and Hindi. A few test queries resemble examples in the classifier prompt, so real-world accuracy is likely somewhat lower.
