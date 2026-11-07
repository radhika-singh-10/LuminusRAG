# Evaluating RAG Systems

A RAG system can fail in two places, so retrieval and generation should be
measured separately. If the right passage was never retrieved, no prompt
change will fix the answer.

## Retrieval metrics

Precision at k is the share of the top k results that are relevant. Recall at k
is the share of all relevant items that appear in the top k. Mean reciprocal
rank, or MRR, averages 1 divided by the rank of the first relevant result, so
it rewards putting a good result first. nDCG also rewards good ordering, and it
discounts relevant results by the logarithm of their position.

## Generation metrics

Faithfulness measures whether the claims in an answer are supported by the
retrieved context. An answer can be faithful and still wrong if the context
itself was wrong. Answer relevance measures whether the response addresses the
question that was asked.

Token F1 compares the words of an answer with a reference answer. It is cheap
to compute but penalizes correct paraphrases.

## Reliability metrics

Language models are stochastic, so one run can hide inconsistency. pass@k is the
probability that at least one of k attempts succeeds, which suits tasks where a
result can be verified afterwards. pass^k is the probability that all k attempts
succeed, which suits systems that users must be able to rely on every time.
pass@k rises as k grows, while pass^k falls.

## Unanswerable questions

An evaluation set should include questions the corpus cannot answer. A system
that always answers will look strong on answerable questions while hallucinating
on the rest. Abstention precision and recall measure whether the system says it
does not know at the right times.
