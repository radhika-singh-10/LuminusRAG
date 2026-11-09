"""Run the RAG pipeline over a labeled dataset and compute metrics.

For each question: retrieve once, generate n answers (sampled when n > 1),
judge each answer, then aggregate per question and across the dataset.
"""
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from .. import config
from ..chain import build_answer_chain, get_llm
from ..store import get_retriever
from . import metrics as M
from .latency import fmt_stats, latency_stats, timer
from .dataset import EvalItem, load_dataset
from .truthfulness import THRESHOLD, get_scorer


def judge(item: EvalItem, answer: str, contexts: list[str], nli) -> dict:
    refused = M.is_refusal(answer)
    out = {"answer": answer, "refused": refused}

    if not item.answerable:
        out["correct"] = refused
        out["hallucinated"] = not refused
        if config.LLM_JUDGE:
            from .llm_judge import judge_answer

            out.update(judge_answer(item.question, "", answer, answerable=False))
        return out

    p, r, f1 = M.token_prf(answer, item.reference) if item.reference else (0.0, 0.0, 0.0)
    out.update(token_precision=p, token_recall=r, token_f1=f1)
    out.update(M.citation_metrics(answer, len(contexts)))
    out.update(nli.faithfulness(answer, contexts))
    if item.reference:
        out["reference_entailment"] = nli.entails(answer, item.reference)

    if config.LLM_JUDGE:
        from .llm_judge import judge_answer

        out.update(judge_answer(item.question, item.reference, answer, item.answerable))

    if refused:
        correct = False
    elif item.must_include:
        correct = M.contains_all(answer, item.must_include)
    else:
        correct = f1 >= 0.5 or out.get("reference_entailment", 0.0) >= THRESHOLD
    out["correct"] = correct
    if out["faithfulness"] is None:
        out["hallucinated"] = None
    else:
        out["hallucinated"] = out["faithfulness"] < 1.0 or out["contradiction_rate"] > 0
    return out


def _generate_timed(answer_chain, docs, question: str) -> tuple[str, dict]:
    """Stream the answer, timing time-to-first-token and total generation."""
    t0 = time.perf_counter()
    first, parts = None, []
    for chunk in answer_chain.stream({"context": docs, "question": question}):
        if first is None and chunk:
            first = time.perf_counter()
        parts.append(chunk)
    end = time.perf_counter()
    answer = "".join(parts)
    tokens = _count_tokens(answer)
    total_s = end - t0  # whole generation: short answers arrive in one chunk, so
    #                     first-to-last-token time is ~0 and would inflate the rate
    return answer, {"ttft_ms": round(((first or end) - t0) * 1000, 1),
                    "generate_ms": round(total_s * 1000, 1), "output_tokens": tokens,
                    "tokens_per_s": round(tokens / total_s, 1) if total_s > 0 and tokens else None}


def _count_tokens(text: str) -> int:
    if config.LLM_PROVIDER == "huggingface":
        from ..chain import _load_hf_model

        return len(_load_hf_model(config.HF_LLM_MODEL)[0].encode(text, add_special_tokens=False))
    if config.LLM_PROVIDER == "mlx":
        from ..mlx_chat import _load_model

        _, tokenizer = _load_model(config.MLX_MODEL_PATH, config.MLX_ADAPTER_PATH)
        return len(tokenizer.encode(text))
    return len(text.split())


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def run_eval(
    dataset: Path | None = None,
    n: int = 5,
    ks: tuple[int, ...] = (1, 3, 5),
    temperature: float = 0.7,
    top_k: int | None = None,
    limit: int | None = None,
) -> dict:
    items = load_dataset(dataset or config.EVAL_DATASET)[:limit]
    ks = tuple(k for k in ks if k <= n)
    temperature = temperature if n > 1 else 0.0

    retriever = get_retriever(top_k)
    answer_chain = build_answer_chain(get_llm(temperature))
    nli = get_scorer()

    per_question = []
    t0 = time.time()
    for qi, item in enumerate(items, 1):
        question = item.question
        lat: dict = {}
        if item.history:
            from ..followup import standalone_question

            with timer(lat, "rewrite_ms"):
                question = standalone_question(item.question, item.history)
        with timer(lat, "retrieve_ms"):
            docs = retriever.invoke(question)
        contexts = [d.page_content for d in docs]
        samples = []
        for _ in range(n):
            answer, gen = _generate_timed(answer_chain, docs, question)
            sample = judge(item, answer, contexts, nli)
            sample.update(gen, end_to_end_ms=round(lat.get("rewrite_ms", 0) + lat["retrieve_ms"]
                                                     + gen["generate_ms"], 1))
            samples.append(sample)
        c = sum(s["correct"] for s in samples)

        row = {
            "id": item.id,
            "question": item.question,
            "answerable": item.answerable,
            "n": n,
            "n_correct": c,
            "accuracy": c / n,
            "standalone_question": question if question != item.question else None,
            "sources": [d.metadata.get("source") for d in docs],
            "latency": lat,
            "samples": samples,
        }
        if item.answerable and item.evidence:
            row["retrieval"] = M.retrieval_metrics(contexts, item.evidence)
        for k in ks:
            row[f"pass@{k}"] = M.pass_at_k(n, c, k)
            row[f"pass^{k}"] = M.pass_hat_k(n, c, k)
        per_question.append(row)
        print(f"  [{qi}/{len(items)}] {item.id}: {c}/{n} correct")

    summary = summarize(per_question, ks)
    summary["config"] = {
        "dataset": str(dataset or config.EVAL_DATASET),
        "llm": (
            config.LLM_MODEL if config.LLM_PROVIDER == "anthropic" else
            f"{config.MLX_MODEL_PATH} + adapter:{config.MLX_ADAPTER_PATH}"
            if config.LLM_PROVIDER == "mlx" else config.HF_LLM_MODEL
        ),
        "embed_model": config.EMBED_MODEL,
        "nli_model": config.NLI_MODEL,
        "top_k": top_k or config.TOP_K,
        "search_type": config.SEARCH_TYPE,
        "retrieval_mode": config.RETRIEVAL_MODE,
        "rerank": config.RERANK,
        "history_aware": config.HISTORY_AWARE,
        "llm_judge": config.JUDGE_MODEL if config.LLM_JUDGE else None,
        "n_samples": n,
        "temperature": temperature,
        "n_questions": len(items),
        "seconds": round(time.time() - t0, 1),
    }
    out_dir = save(per_question, summary)
    summary["results_dir"] = str(out_dir)
    return summary


def summarize(rows: list[dict], ks: tuple[int, ...]) -> dict:
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    ans_samples = [s for r in ans for s in r["samples"]]
    all_samples = [s for r in rows for s in r["samples"]]

    s: dict = {
        "accuracy": _mean(r["accuracy"] for r in rows),
        "accuracy_answerable": _mean(r["accuracy"] for r in ans),
    }
    for k in ks:
        s[f"pass@{k}"] = _mean(r[f"pass@{k}"] for r in rows)
        s[f"pass^{k}"] = _mean(r[f"pass^{k}"] for r in rows)

    retr = [r["retrieval"] for r in ans if "retrieval" in r]
    s["retrieval"] = {m: _mean(x[m] for x in retr) for m in retr[0]} if retr else {}

    s["answer"] = {
        "token_precision": _mean(x.get("token_precision") for x in ans_samples),
        "token_recall": _mean(x.get("token_recall") for x in ans_samples),
        "token_f1": _mean(x.get("token_f1") for x in ans_samples),
        "citation_rate": _mean(x.get("has_citation") for x in ans_samples),
        "citation_validity": _mean(x.get("citation_valid") for x in ans_samples),
    }
    s["truthfulness"] = {
        "faithfulness": _mean(x.get("faithfulness") for x in ans_samples),
        "contradiction_rate": _mean(x.get("contradiction_rate") for x in ans_samples),
        "reference_entailment": _mean(x.get("reference_entailment") for x in ans_samples),
        "hallucination_rate": _mean(
            None if x["hallucinated"] is None else float(x["hallucinated"]) for x in all_samples
        ),
        "claim_coverage": _mean(float(x["faithfulness"] is not None) for x in ans_samples),
    }
    judged = [x for x in all_samples if x.get("judge_correct") is not None]
    if judged:
        from .llm_judge import cohen_kappa

        s["llm_judge"] = {
            "judge_accuracy": _mean(float(x["judge_correct"]) for x in judged),
            "rule_accuracy": _mean(float(x["correct"]) for x in judged),
            "agreement": _mean(float(x["judge_correct"] == x["correct"]) for x in judged),
            "cohen_kappa": cohen_kappa([x["judge_correct"] for x in judged],
                                       [x["correct"] for x in judged]),
            "mean_score": _mean(x["judge_score"] for x in judged),
        }
    # Abstention as a binary classifier: positive = "should say I don't know".
    tp = sum(x["refused"] for r in unans for x in r["samples"])
    fn = sum(not x["refused"] for r in unans for x in r["samples"])
    fp = sum(x["refused"] for x in ans_samples)
    s["abstention"] = M.classification_prf(tp, fp, fn)
    s["latency"] = {
        "end_to_end_ms": latency_stats(x.get("end_to_end_ms") for x in all_samples),
        "ttft_ms": latency_stats(x.get("ttft_ms") for x in all_samples),
        "generate_ms": latency_stats(x.get("generate_ms") for x in all_samples),
        "retrieve_ms": latency_stats(r["latency"].get("retrieve_ms") for r in rows if r.get("latency")),
        "rewrite_ms": latency_stats(r["latency"].get("rewrite_ms") for r in rows if r.get("latency")),
        "tokens_per_s": latency_stats(x.get("tokens_per_s") for x in all_samples),
    }
    return s


def save(rows: list[dict], summary: dict) -> Path:
    out_dir = config.EVAL_RESULTS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "per_question.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=float) + "\n")
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=float)
    return out_dir


def print_report(s: dict) -> None:
    def fmt(v):
        return "  n/a" if v is None else f"{v:6.3f}"

    cfg = s["config"]
    print(f"\nEval: {cfg['n_questions']} questions x {cfg['n_samples']} samples "
          f"(T={cfg['temperature']}, top_k={cfg['top_k']}, llm={cfg['llm']}) "
          f"in {cfg['seconds']}s")
    print("\nGeneration")
    print(f"  accuracy (all)          {fmt(s['accuracy'])}")
    print(f"  accuracy (answerable)   {fmt(s['accuracy_answerable'])}")
    for key in s:
        if key.startswith("pass"):
            print(f"  {key:<23} {fmt(s[key])}")
    for section in ("retrieval", "answer", "truthfulness", "abstention", "llm_judge"):
        if s.get(section):
            print(f"\n{section.capitalize()}")
            for k, v in s[section].items():
                print(f"  {k:<23} {fmt(v)}")
    if lat := s.get("latency"):
        print("\nLatency")
        for k, v in lat.items():
            if not v:
                continue
            if k == "tokens_per_s":
                print(f"  {k:<23} p50 {v['p50']} tok/s, mean {v['mean']} tok/s")
            else:
                print(f"  {k:<23} {fmt_stats(v)}")
    print(f"\nSaved to {s['results_dir']}\n")
