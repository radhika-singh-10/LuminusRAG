# Fine-tuning data

The JSONL files are curated synthetic chat examples grounded in the checked-in `data/*.md` guides. They use the same system prompt and context formatting as `rag/chain.py` and are built by `python finetune/build_dataset.py`.

| Split | Examples | Use |
|---|---:|---|
| `train.jsonl` | 45 | Gradient updates |
| `valid.jsonl` | 8 | Validation during training |
| `test.jsonl` | 10 | Final MLX-LM held-out loss check |

The examples cover context-grounded answers, citation use, abstention when evidence is missing, prompt-injection text inside retrieved context, and core RAG concepts. The builder checks that questions are unique across these splits and that none is an exact copy of a question in `eval/dataset.jsonl`.

## Limits

This is a small seed dataset for pipeline experiments, not a production-quality fine-tuning corpus. The split is question-level, not document- or concept-level, and the project RAG benchmark covers some of the same subject matter. Use the existing `eval/dataset.jsonl` to compare the full RAG pipeline, but do not treat this small synthetic set as an independent scientific benchmark. For stronger evaluation, add human-reviewed questions from held-out source documents and keep them separate from all training examples.

These are SFT chat records. They are not PPO or DPO preference examples; those require explicit preference/reward data and a separate training workflow.
