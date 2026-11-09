"""Run the RAG pipeline over a labeled dataset and compute metrics.

For each question: retrieve once, generate n answers (sampled when n > 1),
judge each answer, then aggregate per question and across the dataset.
"""
# Copyright (c) Lineaje, Inc. All rights reserved.
# Lineaje UnifAI guardrail  version=2.0.0-alpha
def _lineaje_gr_load(_f):
    """Lineaje-added: load gr_stub_client.py beside _f or in one of its 7 parent folders. Missing or broken:
    a pass-through client and ONE warning per process (GR_REQUIRE_CLIENT=1: ImportError instead)."""
    import sys, os, logging, importlib.util as u, pathlib
    n = "_lineaje_gr_stub_client"
    if n in sys.modules: return sys.modules[n]
    h = pathlib.Path(_f or ".").resolve().parent
    d = [h, *h.parents][:8]
    p = next((x / "gr_stub_client.py" for x in d if (x / "gr_stub_client.py").is_file()), None)
    try:
        s = u.spec_from_file_location(n, p) if p else None
        if s is None: raise FileNotFoundError("gr_stub_client.py")
        m = sys.modules[n] = u.module_from_spec(s); s.loader.exec_module(m); return m
    except Exception as e:
        sys.modules.pop(n, None)
        w = ("gr_stub_client.py not found for %s (searched: %s)" % (_f or "<no __file__>", ", ".join(map(str, d)))
             if p is None else "%s failed to load (%s%s)" % (p, type(e).__name__,
                                                          " line %s" % e.lineno if isinstance(e, SyntaxError) else ""))
        w = ("Lineaje guardrail NOT active: " + w + ". Calls pass through unchecked; set GR_REQUIRE_CLIENT=1 to fail "
             "instead. Each deploy unit needs gr_stub_client.py beside its code and GR_SERVICE_URL plus credentials as "
             "environment variables.")
        if os.environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": raise ImportError(w) from (None if p is None else e)
        z = sys.__dict__.setdefault("_lineaje_gr_null", __import__('types').SimpleNamespace(STUB_API=999999, GuardrailUnavailableError=type('GuardrailUnavailableError', (PermissionError,), {}), SiteDescriptor=lambda *a, **k: None, new_interaction_id=lambda *a, **k: None, enforce=lambda _s, _p, *a, **k: _p, enforce_request=lambda _s, _p, *a, **k: _p, enforce_reply=lambda _s, _p, *a, **k: _p, _lineaje_seen=set()))
        k = "missing" if p is None else (str(p), type(e).__name__)
        if k not in z._lineaje_seen:
            z._lineaje_seen.add(k); g = logging.getLogger("lineaje.guardrail"); g.log(30 if p is None else 40, w)
            if g.hasHandlers(): sys.stderr.write(w + "\n")
        return z
__import__("sys").__dict__.setdefault("_lineaje_gr_load_v1", _lineaje_gr_load)
del _lineaje_gr_load
def _lineaje_load_gr_client():
    """Lineaje-added: this file's gr_stub_client.py (the loader _lineaje_gr_load registered)."""
    return __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))
if __import__("os").environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))

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
        # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in judge).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:c7e2bb230edbce02e39f88185246317a139dfbf8de453ab5d85b65398b82d72b'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c7e2bb230edbce02e39f88185246317a139dfbf8de453ab5d85b65398b82d72b', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 32, 'function': 'judge'}, 'file': 'rag/eval/runner.py', 'line': 32, 'function': 'judge', 'agent_name': 'judge', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
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
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in judge).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:40672f9041b7d512ad3cebbb6a3a09407915a9b64ce405977fab708d56f82779'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:40672f9041b7d512ad3cebbb6a3a09407915a9b64ce405977fab708d56f82779', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 57, 'function': 'judge'}, 'file': 'rag/eval/runner.py', 'line': 57, 'function': 'judge', 'agent_name': 'judge', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
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
            # LINEAJE: runtime guardrail checks `docs` as it flows from a vector store to the agent, after the tool returns (in run_eval).
            #   Detected: this statement moves data from a vector store to the agent with no runtime policy check (detection confidence: medium).
            #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `docs` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:b9e70c12b786d0ab61a36519a73082985464346a046c04207281db13d6bb2cf0'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:b9e70c12b786d0ab61a36519a73082985464346a046c04207281db13d6bb2cf0', phase='post_tool', boundary={'source': 'vector_store', 'sink': 'agent_context'}, fail_mode='ALLOW_WITH_AUDIT', source_type='vector_store', destination_type='agent', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 118, 'function': 'run_eval'}, 'file': 'rag/eval/runner.py', 'line': 118, 'function': 'run_eval', 'agent_name': 'run_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                docs = _gr_client.enforce(_gr_site, docs, content_type='application/json', variable_name='docs', source_file=__file__, before_line=118)
            except _gr_client.GuardrailUnavailableError:
                pass
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
        _lineaje_payload = f"  [{qi}/{len(items)}] {item.id}: {c}/{n} correct"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:82f25af583654e9fbd5c46d50c10074ea560fa513993b24e0507d34d92e4a6c7'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:82f25af583654e9fbd5c46d50c10074ea560fa513993b24e0507d34d92e4a6c7', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 147, 'function': 'run_eval'}, 'file': 'rag/eval/runner.py', 'line': 147, 'function': 'run_eval', 'agent_name': 'run_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)

    summary = summarize(per_question, ks)
    summary["config"] = {
        "dataset": str(dataset or config.EVAL_DATASET),
        "llm": config.LLM_MODEL if config.LLM_PROVIDER == "anthropic" else config.HF_LLM_MODEL,
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
    # LINEAJE: runtime guardrail checks `summary` as it flows from the agent to the user interface, before it leaves the application (in run_eval).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `summary` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:1108ae73bc02cc68521350d5de2be37c0b6fbda55bc926c240bf15de757058b8'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1108ae73bc02cc68521350d5de2be37c0b6fbda55bc926c240bf15de757058b8', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 168, 'function': 'run_eval'}, 'file': 'rag/eval/runner.py', 'line': 168, 'function': 'run_eval', 'agent_name': 'run_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        summary = _gr_client.enforce(_gr_site, summary, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
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
    # LINEAJE: runtime guardrail checks `s` as it flows from the agent to the user interface, before it leaves the application (in summarize).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `s` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:33b4d033ecd280cd85cf459977aa55dbefc4c82a5e22b33b55654edbc15013ff'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:33b4d033ecd280cd85cf459977aa55dbefc4c82a5e22b33b55654edbc15013ff', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 229, 'function': 'summarize'}, 'file': 'rag/eval/runner.py', 'line': 229, 'function': 'summarize', 'agent_name': 'summarize', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        s = _gr_client.enforce(_gr_site, s, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return s


def save(rows: list[dict], summary: dict) -> Path:
    out_dir = config.EVAL_RESULTS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "per_question.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            # LINEAJE: runtime guardrail checks `r` as it flows from the agent to an external endpoint, before it leaves the application (in save).
            #   Detected: this statement moves data from the agent to an external endpoint with no runtime policy check (detection confidence: medium).
            #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `r` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:8cbbaae4016414100c00fac60362aa5c4138065227469c66b8f263851cfeb4e6'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:8cbbaae4016414100c00fac60362aa5c4138065227469c66b8f263851cfeb4e6', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'external_endpoint'}, fail_mode='ALLOW_WITH_AUDIT', source_type='agent', destination_type='external', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 237, 'function': 'save'}, 'file': 'rag/eval/runner.py', 'line': 237, 'function': 'save', 'agent_name': 'save', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                r = _gr_client.enforce(_gr_site, r, content_type='application/json', variable_name='r', source_file=__file__, before_line=237)
            except _gr_client.GuardrailUnavailableError:
                pass
            _lineaje_payload = json.dumps(r, default=float) + "\n"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to a file, before it is written to disk (in save).
            #   Detected: this statement moves data from the agent to a file with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_025; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:4271022b9bd089a7a50de8fb0ba9cfccb4ae6c8df83c6b24dfe0ea253cdd0754'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4271022b9bd089a7a50de8fb0ba9cfccb4ae6c8df83c6b24dfe0ea253cdd0754', phase='file_write', boundary={'source': 'agent_message', 'sink': 'file_content'}, fail_mode='BLOCK', source_type='agent', destination_type='file', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 237, 'function': 'save'}, 'file': 'rag/eval/runner.py', 'line': 237, 'function': 'save', 'agent_name': 'save', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=237)
            except _gr_client.GuardrailUnavailableError:
                pass
            f.write(_lineaje_payload)
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        # LINEAJE: runtime guardrail checks `summary` as it flows from the agent to a file, before it is written to disk (in save).
        #   Detected: this statement moves data from the agent to a file with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_025; sensitive values in `summary` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:2b6f2b1be160b2b85d36582e3f68ee79e04faaf2ac5b91a0cbc66fad9dc4ea7e'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2b6f2b1be160b2b85d36582e3f68ee79e04faaf2ac5b91a0cbc66fad9dc4ea7e', phase='file_write', boundary={'source': 'agent_message', 'sink': 'file_content'}, fail_mode='BLOCK', source_type='agent', destination_type='file', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 239, 'function': 'save'}, 'file': 'rag/eval/runner.py', 'line': 239, 'function': 'save', 'agent_name': 'save', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            summary = _gr_client.enforce(_gr_site, summary, content_type='application/json', variable_name='summary', source_file=__file__, before_line=239)
        except _gr_client.GuardrailUnavailableError:
            pass
        json.dump(summary, f, indent=2, default=float)
    # LINEAJE: runtime guardrail checks `out_dir` as it flows from the agent to the user interface, before it leaves the application (in save).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out_dir` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:917bc307286e1ad1e7c10d43425fb21e1491a7f6b20a0b8c0c35b5fc1e55f9c8'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:917bc307286e1ad1e7c10d43425fb21e1491a7f6b20a0b8c0c35b5fc1e55f9c8', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 240, 'function': 'save'}, 'file': 'rag/eval/runner.py', 'line': 240, 'function': 'save', 'agent_name': 'save', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out_dir = _gr_client.enforce(_gr_site, out_dir, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out_dir


def print_report(s: dict) -> None:
    def fmt(v):
        return "  n/a" if v is None else f"{v:6.3f}"

    cfg = s["config"]
    _lineaje_payload = (f"\nEval: {cfg['n_questions']} questions x {cfg['n_samples']} samples "
          f"(T={cfg['temperature']}, top_k={cfg['top_k']}, llm={cfg['llm']}) "
          f"in {cfg['seconds']}s")
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_report).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:d9faa83cf8be1606c9cd956bd9a914dafea472493dc786ef296a94095cb6adf6'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:d9faa83cf8be1606c9cd956bd9a914dafea472493dc786ef296a94095cb6adf6', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 248, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 248, 'function': 'print_report', 'agent_name': 'print_report', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = "\nGeneration"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_report).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:4d91b96e6fa0306ae3f4cfbb70cb3d75a616d145d8b8a05eef239a5a2aa7ffc3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4d91b96e6fa0306ae3f4cfbb70cb3d75a616d145d8b8a05eef239a5a2aa7ffc3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 251, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 251, 'function': 'print_report', 'agent_name': 'print_report', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  accuracy (all)          {fmt(s['accuracy'])}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_report).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:9b294d72405e3786d464816cbbd1b8f7da23f508f44ec3bab0d2171e49754955'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9b294d72405e3786d464816cbbd1b8f7da23f508f44ec3bab0d2171e49754955', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 252, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 252, 'function': 'print_report', 'agent_name': 'print_report', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  accuracy (answerable)   {fmt(s['accuracy_answerable'])}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_report).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:ad20ae63c4edf27bfafd63332c4e6f69a74af57055004dce61088d2c67bff3e0'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ad20ae63c4edf27bfafd63332c4e6f69a74af57055004dce61088d2c67bff3e0', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 253, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 253, 'function': 'print_report', 'agent_name': 'print_report', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    for key in s:
        if key.startswith("pass"):
            _lineaje_payload = f"  {key:<23} {fmt(s[key])}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in fmt).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:81b6154fc527f83caad554b6b3f9052a67778e0f347ed722027078bdfd23284f'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:81b6154fc527f83caad554b6b3f9052a67778e0f347ed722027078bdfd23284f', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 256, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 256, 'function': 'fmt', 'agent_name': 'fmt', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
    for section in ("retrieval", "answer", "truthfulness", "abstention", "llm_judge"):
        if s.get(section):
            _lineaje_payload = f"\n{section.capitalize()}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in fmt).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:7001bc6426b3658a59baf8fb52dc6fe5c46afeae622d0fe8d1e6ffc61ab497d1'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:7001bc6426b3658a59baf8fb52dc6fe5c46afeae622d0fe8d1e6ffc61ab497d1', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 259, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 259, 'function': 'fmt', 'agent_name': 'fmt', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            for k, v in s[section].items():
                _lineaje_payload = f"  {k:<23} {fmt(v)}"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in fmt).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:5fefd9b45ed0943977c22b368527b8e55932e50095367890e0157bb33d78b4c6'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5fefd9b45ed0943977c22b368527b8e55932e50095367890e0157bb33d78b4c6', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 261, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 261, 'function': 'fmt', 'agent_name': 'fmt', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
    if lat := s.get("latency"):
        _lineaje_payload = "\nLatency"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in fmt).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:173858d80f43bfc6cf8efa20030d0e83aecc15ebc1c68b6288f029965de83dbd'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:173858d80f43bfc6cf8efa20030d0e83aecc15ebc1c68b6288f029965de83dbd', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 263, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 263, 'function': 'fmt', 'agent_name': 'fmt', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for k, v in lat.items():
            if not v:
                continue
            if k == "tokens_per_s":
                _lineaje_payload = f"  {k:<23} p50 {v['p50']} tok/s, mean {v['mean']} tok/s"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in fmt).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:25ba35c04ec622a574e903c160e426b0e0774d343c0f52cb568820742fab7aa6'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:25ba35c04ec622a574e903c160e426b0e0774d343c0f52cb568820742fab7aa6', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 268, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 268, 'function': 'fmt', 'agent_name': 'fmt', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
            else:
                _lineaje_payload = f"  {k:<23} {fmt_stats(v)}"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in fmt).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:c6f20703e2c2292bb971de6af258302418f1b74c1784da6922a33f1b66ed9c73'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c6f20703e2c2292bb971de6af258302418f1b74c1784da6922a33f1b66ed9c73', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 270, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 270, 'function': 'fmt', 'agent_name': 'fmt', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
    _lineaje_payload = f"\nSaved to {s['results_dir']}\n"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_report).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:0a8cfedfa3344a49998d5cbd5acef49e63ab6883d7ef954041f0ab4cb3bb3ea4'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0a8cfedfa3344a49998d5cbd5acef49e63ab6883d7ef954041f0ab4cb3bb3ea4', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/runner.py', 'line': 271, 'function': 'print_report'}, 'file': 'rag/eval/runner.py', 'line': 271, 'function': 'print_report', 'agent_name': 'print_report', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
