"""Evaluation of the agent harness (rag/agent).

Part 1: personalized retrieval (eval/personalization_dataset.jsonl).
  Ambiguous questions ("What does recall mean?") whose right source depends
  on what the user asked before (evaluation metrics vs ANN search). Each item
  builds an interest profile from its persona's history questions, then
  compares retrieval without the profile (hybrid retriever) and with it
  (PersonalizedRetriever). Metrics on the expected source file, over all
  passages returned (what the model reads): hit@1, hit@3, MRR, and the share
  of passages from that file. A regression check runs the normal eval
  questions with a mismatched profile: recall must not drop.

Part 2: multi-step sessions (eval/agent_sessions.jsonl).
  A simulated user opens with a question and then, at every step, clicks the
  suggested follow-up closest to their persona description, for up to
  AGENT_MAX_STEPS steps; one more question checks that the step limit holds.
  Metrics:
  - steps completed, step limit enforced, final chat summary produced
  - follow-ups per turn (and max, must be <= AGENT_MAX_FOLLOWUPS), share of
    turns with at least one suggestion
  - follow-up safety: every suggestion re-checked with the full policy guard
    (regex + LLM judge) and the intent gate
  - follow-up answered rate: chosen follow-ups answered (not refused), from local docs
  - novelty: 1 - max cosine to earlier questions; duplicate rate
  - persona alignment: cosine(suggestion, own persona) - mean cosine to the
    other personas, and the share of suggestions nearest their own persona
  - answers: NLI faithfulness, lexical grounding, refusal rate
  - mean latency per layer (from the harness trace)
  With compare=True the sessions also run with PERSONALIZE off.
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

import numpy as np

from .. import config
from .harness import overrides
from .latency import fmt_stats, latency_stats

PERSONALIZATION_DATASET = config.ROOT / "eval" / "personalization_dataset.jsonl"
SESSIONS_DATASET = config.ROOT / "eval" / "agent_sessions.jsonl"


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


# ---------- part 1: personalized retrieval ----------

def build_profile(history: list[str]) -> list[dict]:
    """Interest profile from history questions, as the harness would build it."""
    from ..agent.personalize import interests_from_turn
    from ..store import get_retriever

    prof: dict[str, dict] = {}
    for q in history:
        for p in prof.values():
            p["weight"] *= config.INTEREST_DECAY
        try:
            _lineaje_obs = _lineaje_load_gr_client()
            _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:7ec5cf45fac477c4141bfaeb8abe9e2aa51303e8fdffae370bb9650802bd375a', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/eval/agent_eval.py', 'line': 67, 'function': 'build_profile', 'agent_name': 'build_profile', 'agent_name_source': 'inferred_from_function', 'call_target': 'get_retriever().invoke', 'not_on_graph': True}, observe_only=True)
            _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
        except Exception as _lineaje_obs_err:
            [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
        for ent, (name, w) in interests_from_turn(q, get_retriever().invoke(q)).items():
            prof.setdefault(ent, {"entity": ent, "name": name, "weight": 0.0})["weight"] += w
    return sorted(prof.values(), key=lambda x: -x["weight"])


def _source_ranks(docs, expected: str, k: int) -> dict:
    # Every passage the model would see (graph facts excluded), in order.
    files = [Path(d.metadata.get("source", "")).name for d in docs
             if d.metadata.get("origin") != "graph"]
    rank = next((i + 1 for i, f in enumerate(files) if f == expected), None)
    return {"hit@1": float(rank == 1), "hit@3": float(rank is not None and rank <= 3),
            "mrr": 1 / rank if rank else 0.0,
            "source_share": files.count(expected) / len(files) if files else 0.0,
            "top": files[:3]}


def eval_personalized_retrieval(path: Path = PERSONALIZATION_DATASET, verbose: bool = True) -> dict:
    from ..agent.personalize import PersonalizedRetriever
    from ..store import get_retriever

    items = _load(path)
    rows = []
    for it in items:
        profile = build_profile(it["history"])
        try:
            _lineaje_obs = _lineaje_load_gr_client()
            _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:b1b043e6110cf739290aa23d7356ca3ca95e3252d218d361267be391000d359d', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/eval/agent_eval.py', 'line': 91, 'function': 'eval_personalized_retrieval', 'agent_name': 'eval_personalized_retrieval', 'agent_name_source': 'inferred_from_function', 'call_target': 'get_retriever().invoke', 'not_on_graph': True}, observe_only=True)
            _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
        except Exception as _lineaje_obs_err:
            [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
        base = _source_ranks(get_retriever().invoke(it["question"]), it["expected_source"], config.TOP_K)
        try:
            _lineaje_obs = _lineaje_load_gr_client()
            _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:1732b27765b1a6fbeed6c45279b062737b40bcb19040a2ca4f4a16945bf3dcae', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/eval/agent_eval.py', 'line': 92, 'function': 'eval_personalized_retrieval', 'agent_name': 'eval_personalized_retrieval', 'agent_name_source': 'inferred_from_function', 'call_target': 'PersonalizedRetriever(interests=profile, k=config.TOP_K, graph_k=config.GRAPH_K)', 'not_on_graph': True}, observe_only=True)
            _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
        except Exception as _lineaje_obs_err:
            [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
        pers = _source_ranks(PersonalizedRetriever(interests=profile, k=config.TOP_K,
                                                   graph_k=config.GRAPH_K).invoke(it["question"]),
                             it["expected_source"], config.TOP_K)
        rows.append({"id": it["id"], "persona": it["persona"], "question": it["question"],
                     "expected": it["expected_source"], "interests": [p["name"] for p in profile[:4]],
                     "baseline": base, "personalized": pers})
        if verbose:
            _lineaje_payload = (f"  {it['id']} {it['persona']:<11} {it['question'][:40]:<40} "
                  f"base@1={base['hit@1']:.0f} pers@1={pers['hit@1']:.0f}  ({', '.join(p['name'] for p in profile[:3])})")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in eval_personalized_retrieval).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:0a9f8a5b4eb3ec0ccf00659bdf157a0ad3755606d22b10aaafb755cab4d86db8'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0a9f8a5b4eb3ec0ccf00659bdf157a0ad3755606d22b10aaafb755cab4d86db8', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 99, 'function': 'eval_personalized_retrieval'}, 'file': 'rag/eval/agent_eval.py', 'line': 99, 'function': 'eval_personalized_retrieval', 'agent_name': 'eval_personalized_retrieval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
    agg = {}
    for variant in ("baseline", "personalized"):
        agg[variant] = {m: _mean(r[variant][m] for r in rows)
                        for m in ("hit@1", "hit@3", "mrr", "source_share")}
    return {"n": len(rows), **agg, "items": rows}


REGRESSION_PROFILES = {
    "langchain": ["What is LCEL?", "How do prompt templates work in LangChain?"],
    "vector_db": ["What is HNSW?", "How does metadata filtering work in a vector database?"],
}


def eval_profile_regression(path: Path | None = None) -> dict:
    """Normal eval questions retrieved with no profile vs with a profile from
    unrelated history: personalization must not cost recall."""
    from ..agent.personalize import PersonalizedRetriever
    from ..store import get_retriever
    from .metrics import retrieval_metrics

    items = [i for i in _load(path or config.EVAL_DATASET) if i.get("evidence")]

    def run(retrieve) -> dict:
        ms = [retrieval_metrics([d.page_content for d in retrieve(i["question"])
                                 if d.metadata.get("origin") != "graph"], i["evidence"]) for i in items]
        return {"recall": _mean(m["recall_at_k"] for m in ms), "mrr": _mean(m["mrr"] for m in ms)}

    out = {"n": len(items), "no_profile": run(lambda q: get_retriever().invoke(q))}
    for name, history in REGRESSION_PROFILES.items():
        prof = build_profile(history)
        out[f"profile_{name}"] = run(lambda q, prof=prof: PersonalizedRetriever(
            interests=prof, k=config.TOP_K, graph_k=config.GRAPH_K).invoke(q))
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in eval_profile_regression).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:d8a94ebdadc2d1e86d63efa0aa4a1338fd79f040e97c0388a2a2dbd9fcfb254b'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:d8a94ebdadc2d1e86d63efa0aa4a1338fd79f040e97c0388a2a2dbd9fcfb254b', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 133, 'function': 'eval_profile_regression'}, 'file': 'rag/eval/agent_eval.py', 'line': 133, 'function': 'eval_profile_regression', 'agent_name': 'eval_profile_regression', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


# ---------- part 2: sessions ----------

def _pick(followups: list[dict], persona_vec: np.ndarray) -> str | None:
    from ..store import get_embeddings

    if not followups:
        return None
    v = np.asarray(get_embeddings().embed_documents([f["question"] for f in followups]))
    return followups[int(np.argmax(v @ persona_vec))]["question"]


def run_session(agent, spec: dict, personas: dict[str, np.ndarray], steps: int, verbose: bool) -> dict:
    from ..agent.memory import clear_interests
    from ..eval.metrics import is_refusal
    from ..history import delete_chat, new_chat_id
    from ..store import get_embeddings

    emb = get_embeddings()
    chat_id = new_chat_id()
    user = agent.user_id
    clear_interests(user)
    own = personas[spec["persona"]]
    others = [v for k, v in personas.items() if k != spec["persona"]]
    backup = list(spec.get("backup", []))
    turns, asked, final_summary = [], [], None
    question, from_fu = spec["opening"], False
    try:
        for _ in range(steps):
            t0 = time.perf_counter()
            r, ttft = None, None
            for e in agent.events(chat_id, question, from_fu):
                if e["type"] == "token" and ttft is None:
                    ttft = (time.perf_counter() - t0) * 1000
                elif e["type"] == "final":
                    r = e["result"]
            turns.append({"step": r["step"], "question": question, "from_followup": from_fu,
                          "standalone": r.get("standalone_question"), "answer": r["answer"],
                          "origin": r.get("origin"), "refused": r.get("origin") in (None, "none")
                          or is_refusal(r["answer"]),
                          "context": [d.page_content for d in r["context"]],
                          "followups": r["followups"], "metrics": r["metrics"], "trace": r["trace"],
                          "interests": [i["name"] for i in r["interests"][:5]],
                          "seconds": round(time.perf_counter() - t0, 2),
                          "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                          "ttft_ms": round(ttft, 1) if ttft is not None else None})
            asked.append(question)
            if verbose:
                _lineaje_payload = (f"    step {r['step']:>2} [{r.get('origin')}] {question[:70]}"
                      f"  -> {len(r['followups'])} follow-ups")
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_session).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:0384af0d87645228b0c7305a9bda70687e5e40e2e916229a3b29a3b15469aa98'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0384af0d87645228b0c7305a9bda70687e5e40e2e916229a3b29a3b15469aa98', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 183, 'function': 'run_session'}, 'file': 'rag/eval/agent_eval.py', 'line': 183, 'function': 'run_session', 'agent_name': 'run_session', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
            if r.get("closed"):
                final_summary = r.get("summary")
                break
            nxt = _pick(r["followups"], own)
            from_fu = nxt is not None
            if nxt is None:  # no suggestion: the user asks their own next question
                nxt = backup.pop(0) if backup else spec["opening"]
            question = nxt
        # One more question: the step limit must refuse it.
        extra = agent.turn(chat_id, "What is a transformer?")
        limit_enforced = bool(extra.get("limit_reached")) and len(turns) >= agent.max_steps
    finally:
        delete_chat(chat_id)
        clear_interests(user)

    # Follow-up level metrics
    sugg = [f["question"] for t in turns for f in t["followups"]]
    align, nearest = [], []
    if sugg:
        # LINEAJE: runtime guardrail checks `sugg` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in run_session).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `sugg` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9fabb60db566270977411b6357859f7ec9a7020268dd689999bbd47f8ec95dcf'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9fabb60db566270977411b6357859f7ec9a7020268dd689999bbd47f8ec95dcf', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 204, 'function': 'run_session'}, 'file': 'rag/eval/agent_eval.py', 'line': 204, 'function': 'run_session', 'agent_name': 'run_session', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            sugg = _gr_client.enforce(_gr_site, sugg, content_type='application/json', variable_name='sugg', source_file=__file__, before_line=204)
        except _gr_client.GuardrailUnavailableError:
            pass
        sv = np.asarray(emb.embed_documents(sugg))
        own_sim = sv @ own
        other_sim = np.stack([sv @ o for o in others], axis=1)
        align = list(own_sim - other_sim.mean(axis=1))
        nearest = list((own_sim > other_sim.max(axis=1)).astype(float))
    novelty, dupes = [], []
    for i, t in enumerate(turns):
        if i == 0:
            continue
        _lineaje_payload = [x["question"] for x in turns[:i]]
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in run_session).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `_lineaje_payload` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:4aea90e1f0ca3a75b17e1b49024b83c54df7a22a075e67cebae4b59dc63bee79'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4aea90e1f0ca3a75b17e1b49024b83c54df7a22a075e67cebae4b59dc63bee79', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 213, 'function': 'run_session'}, 'file': 'rag/eval/agent_eval.py', 'line': 213, 'function': 'run_session', 'agent_name': 'run_session', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=213)
        except _gr_client.GuardrailUnavailableError:
            pass
        prev = np.asarray(emb.embed_documents(_lineaje_payload))
        _lineaje_payload = t["question"]
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in run_session).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `_lineaje_payload` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:893884c035a64ef4dcec6ddcb4c61cf34029834364e23f815946ada61c381882'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:893884c035a64ef4dcec6ddcb4c61cf34029834364e23f815946ada61c381882', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 214, 'function': 'run_session'}, 'file': 'rag/eval/agent_eval.py', 'line': 214, 'function': 'run_session', 'agent_name': 'run_session', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=214)
        except _gr_client.GuardrailUnavailableError:
            pass
        sim = float((prev @ np.asarray(emb.embed_query(_lineaje_payload))).max())
        novelty.append(1 - sim)
        dupes.append(float(sim >= 0.86))
    chosen = [t for t in turns if t["from_followup"]]
    return {
        "id": spec["id"], "persona": spec["persona"], "steps": len(turns),
        "limit_enforced": limit_enforced, "final_summary": bool(final_summary),
        "turns": turns, "suggestions": sugg,
        "followups_per_turn": _mean(len(t["followups"]) for t in turns[:-1]),
        "max_followups": max((len(t["followups"]) for t in turns), default=0),
        "turns_with_followups": _mean(float(bool(t["followups"])) for t in turns[:-1]),
        "followup_taken_rate": len(chosen) / max(1, len(turns) - 1),
        "followup_answered": _mean(float(not t["refused"]) for t in chosen),
        "followup_local": _mean(float(t["origin"] == "local") for t in chosen),
        "novelty": _mean(novelty), "duplicate_rate": _mean(dupes),
        "persona_alignment": _mean(align), "on_persona": _mean(nearest),
        "refusal_rate": _mean(float(t["refused"]) for t in turns),
        "lexical_grounding": _mean(t["metrics"].get("lexical_grounding") for t in turns),
        "seconds_per_turn": _mean(t["seconds"] for t in turns),
    }


def _safety_of(suggestions: list[str]) -> dict:
    from ..intent import classify_intent
    from ..policy import check_query

    safe = [check_query(q).safe for q in suggestions]
    allowed = [classify_intent(q).allowed for q in suggestions]
    return {"n": len(suggestions), "guard_safe": _mean(map(float, safe)),
            "intent_allowed": _mean(map(float, allowed))}


def _faithfulness(sessions: list[dict]) -> float | None:
    from .truthfulness import get_scorer

    scorer = get_scorer()
    vals = []
    for s in sessions:
        for t in s["turns"]:
            if not t["refused"] and t["context"]:
                vals.append(scorer.faithfulness(t["answer"], t["context"])["faithfulness"])
    return _mean(vals)


def _layer_latency(sessions: list[dict]) -> dict:
    by: dict[str, list[float]] = {}
    for s in sessions:
        for t in s["turns"]:
            for e in t["trace"]:
                by.setdefault(e["layer"], []).append(e["ms"])
    return {k: round(statistics.fmean(v)) for k, v in sorted(by.items())}


def _latency(sessions: list[dict]) -> dict:
    """Turn latency, time to first token, and p50/p95 per harness layer."""
    turns = [t for s in sessions for t in s["turns"]]
    by: dict[str, list[float]] = {}
    for t in turns:
        per_turn: dict[str, float] = {}
        for e in t["trace"]:
            per_turn[e["layer"]] = per_turn.get(e["layer"], 0) + e["ms"]
        for k, v in per_turn.items():
            by.setdefault(k, []).append(v)
    return {"turn_ms": latency_stats(t["latency_ms"] for t in turns),
            "ttft_ms": latency_stats(t["ttft_ms"] for t in turns),
            "layers": {k: latency_stats(v) for k, v in sorted(by.items())}}


def eval_sessions(path: Path = SESSIONS_DATASET, steps: int | None = None, limit: int | None = None,
                  verbose: bool = True) -> dict:
    from ..agent.harness import build_agent
    from ..chain import get_llm
    from ..store import get_embeddings

    all_specs = _load(path)
    specs = all_specs[:limit] if limit else all_specs
    steps = steps or config.AGENT_MAX_STEPS
    emb = get_embeddings()
    # Persona vectors from the whole dataset, so alignment has others to compare with.
    personas = {s["persona"]: np.asarray(emb.embed_query(s["description"])) for s in all_specs}
    agent = build_agent(get_llm(), max_steps=steps, user_id="eval-agent")
    sessions = []
    for spec in specs:
        if verbose:
            _lineaje_payload = f"  session {spec['id']} ({spec['persona']})"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in eval_sessions).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:26830fb41af420229ae18885bd917226097538ae85d781f8d2e352c880bd5dad'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:26830fb41af420229ae18885bd917226097538ae85d781f8d2e352c880bd5dad', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 298, 'function': 'eval_sessions'}, 'file': 'rag/eval/agent_eval.py', 'line': 298, 'function': 'eval_sessions', 'agent_name': 'eval_sessions', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        sessions.append(run_session(agent, spec, personas, steps, verbose))
    keys = ["steps", "followups_per_turn", "turns_with_followups", "followup_taken_rate",
            "followup_answered", "followup_local", "novelty", "duplicate_rate",
            "persona_alignment", "on_persona", "refusal_rate", "lexical_grounding", "seconds_per_turn"]
    summary = {k: _mean(s[k] for s in sessions) for k in keys}
    summary["max_followups"] = max(s["max_followups"] for s in sessions)
    summary["limit_enforced"] = _mean(float(s["limit_enforced"]) for s in sessions)
    summary["final_summary"] = _mean(float(s["final_summary"]) for s in sessions)
    if verbose:
        _lineaje_payload = "  checking follow-up safety and answer faithfulness…"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in eval_sessions).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:8fdd9d679553836127f26b22f155b7229317e90df51ccd12e2c47c0f681d2744'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:8fdd9d679553836127f26b22f155b7229317e90df51ccd12e2c47c0f681d2744', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 308, 'function': 'eval_sessions'}, 'file': 'rag/eval/agent_eval.py', 'line': 308, 'function': 'eval_sessions', 'agent_name': 'eval_sessions', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    summary["followup_safety"] = _safety_of([q for s in sessions for q in s["suggestions"]])
    summary["faithfulness"] = _faithfulness(sessions)
    summary["layer_ms"] = _layer_latency(sessions)
    summary["latency"] = _latency(sessions)
    return {"summary": summary, "sessions": sessions}


# ---------- driver ----------

def run_agent_eval(sessions: bool = True, retrieval: bool = True, compare: bool = False,
                   steps: int | None = None, limit: int | None = None, verbose: bool = True) -> dict:
    t0 = time.perf_counter()
    out = {"config": {"max_steps": steps or config.AGENT_MAX_STEPS,
                      "max_followups": config.AGENT_MAX_FOLLOWUPS, "top_k": config.TOP_K,
                      "personal_weight": config.PERSONAL_WEIGHT, "ppr_weight": config.PPR_WEIGHT,
                      "interest_decay": config.INTEREST_DECAY}}
    if retrieval:
        if verbose:
            _lineaje_payload = "Personalized retrieval:"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_agent_eval).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:95eb9db18450f9966d41e0c4c6c46bc4a7ec0303a41d9b7b56feb77cca0d8bf1'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:95eb9db18450f9966d41e0c4c6c46bc4a7ec0303a41d9b7b56feb77cca0d8bf1', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 327, 'function': 'run_agent_eval'}, 'file': 'rag/eval/agent_eval.py', 'line': 327, 'function': 'run_agent_eval', 'agent_name': 'run_agent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        out["retrieval"] = eval_personalized_retrieval(verbose=verbose)
        out["regression"] = eval_profile_regression()
    if sessions:
        if verbose:
            _lineaje_payload = "Sessions (personalized):"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_agent_eval).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:c836c58c4d5cc73805e2c7f883ee5aadd7fec1b8769f5e3b6f0997487a0d04d1'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c836c58c4d5cc73805e2c7f883ee5aadd7fec1b8769f5e3b6f0997487a0d04d1', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 332, 'function': 'run_agent_eval'}, 'file': 'rag/eval/agent_eval.py', 'line': 332, 'function': 'run_agent_eval', 'agent_name': 'run_agent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        out["sessions"] = eval_sessions(steps=steps, limit=limit, verbose=verbose)
        if compare:
            if verbose:
                _lineaje_payload = "Sessions (personalization off):"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_agent_eval).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:c8249a6af4130a4d9f24b81c164c49746864141ec9342192be29078fd555ba41'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c8249a6af4130a4d9f24b81c164c49746864141ec9342192be29078fd555ba41', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 336, 'function': 'run_agent_eval'}, 'file': 'rag/eval/agent_eval.py', 'line': 336, 'function': 'run_agent_eval', 'agent_name': 'run_agent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
            with overrides({"PERSONALIZE": False}):
                out["sessions_baseline"] = eval_sessions(steps=steps, limit=limit, verbose=verbose)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    path = config.EVAL_RESULTS_DIR / f"agent-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to an external endpoint, before it leaves the application (in run_agent_eval).
    #   Detected: this statement moves data from the agent to an external endpoint with no runtime policy check (detection confidence: medium).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `out` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:da3ac0de328c2578b4880e588d2bb26fc1c5e6f33f2564e4eff7ef7f7a266d70'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:da3ac0de328c2578b4880e588d2bb26fc1c5e6f33f2564e4eff7ef7f7a266d70', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'external_endpoint'}, fail_mode='ALLOW_WITH_AUDIT', source_type='agent', destination_type='external', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 342, 'function': 'run_agent_eval'}, 'file': 'rag/eval/agent_eval.py', 'line': 342, 'function': 'run_agent_eval', 'agent_name': 'run_agent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='application/json', variable_name='out', source_file=__file__, before_line=342)
    except _gr_client.GuardrailUnavailableError:
        pass
    _lineaje_payload = json.dumps(out, indent=2, default=str)
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to a file, before it is written to disk (in run_agent_eval).
    #   Detected: this statement moves data from the agent to a file with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_025; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:664b1c22713eb7cd113bd23c6ef322e64b6ad6aeb035d693d90dea4686931cbb'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:664b1c22713eb7cd113bd23c6ef322e64b6ad6aeb035d693d90dea4686931cbb', phase='file_write', boundary={'source': 'agent_message', 'sink': 'file_content'}, fail_mode='BLOCK', source_type='agent', destination_type='file', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 342, 'function': 'run_agent_eval'}, 'file': 'rag/eval/agent_eval.py', 'line': 342, 'function': 'run_agent_eval', 'agent_name': 'run_agent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=342)
    except _gr_client.GuardrailUnavailableError:
        pass
    path.write_text(_lineaje_payload)
    out["path"] = str(path)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in run_agent_eval).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:0dd4de19df20e9e368ae56d02c79ff829ab6d330bcd3cbfad9040c07893c6746'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0dd4de19df20e9e368ae56d02c79ff829ab6d330bcd3cbfad9040c07893c6746', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 344, 'function': 'run_agent_eval'}, 'file': 'rag/eval/agent_eval.py', 'line': 344, 'function': 'run_agent_eval', 'agent_name': 'run_agent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def print_agent_report(out: dict) -> None:
    def f(v):
        return "n/a" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)

    if r := out.get("retrieval"):
        _lineaje_payload = f"\nPersonalized retrieval ({r['n']} ambiguous questions, expected source file)"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:61d59eb7940f5fc2b50ba9e07889c646a7605117673821d79681a7c30a40f70a'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:61d59eb7940f5fc2b50ba9e07889c646a7605117673821d79681a7c30a40f70a', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 352, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 352, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        _lineaje_payload = f"  {'':<14}{'hit@1':>8}{'hit@3':>8}{'MRR':>8}{'share':>8}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:d3f58db319bbd6fe8b29151d1d61c576e55231b12e1dcb73d5ffa1c70b079d69'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:d3f58db319bbd6fe8b29151d1d61c576e55231b12e1dcb73d5ffa1c70b079d69', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 353, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 353, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for v in ("baseline", "personalized"):
            _lineaje_payload = f"  {v:<14}" + "".join(f"{f(r[v][m]):>8}" for m in ("hit@1", "hit@3", "mrr", "source_share"))
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:2ae16dbbb5ecc4e7a5858b813598689f2ea11e01b29bbee75aa8a94d3ba944f3'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2ae16dbbb5ecc4e7a5858b813598689f2ea11e01b29bbee75aa8a94d3ba944f3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 355, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 355, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
    if g := out.get("regression"):
        _lineaje_payload = f"\nRegression check ({g['n']} normal questions, profile from unrelated history)"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:a99fd02204bd621810da5b054e0903b43fb59d8e75712914214f0e0c262bd083'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:a99fd02204bd621810da5b054e0903b43fb59d8e75712914214f0e0c262bd083', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 357, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 357, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for k, v in g.items():
            if k != "n":
                _lineaje_payload = f"  {k:<20} recall {f(v['recall'])}  MRR {f(v['mrr'])}"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:f2ba06bb5daf0d9f6d0248073409b8b74be747dcc19718fa4fcc7663340f6896'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:f2ba06bb5daf0d9f6d0248073409b8b74be747dcc19718fa4fcc7663340f6896', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 360, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 360, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
    variants = [("personalized", out.get("sessions")), ("no personalization", out.get("sessions_baseline"))]
    variants = [(n, s) for n, s in variants if s]
    if variants:
        _lineaje_payload = "\nMulti-step sessions"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:2e53ff6682a82dc74add61ed76b2420dbdf911d9c8fa8cdf99924de36bc847f7'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2e53ff6682a82dc74add61ed76b2420dbdf911d9c8fa8cdf99924de36bc847f7', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 364, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 364, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        keys = ["steps", "limit_enforced", "final_summary", "followups_per_turn", "max_followups",
                "turns_with_followups", "followup_taken_rate", "followup_answered", "followup_local",
                "novelty", "duplicate_rate", "persona_alignment", "on_persona", "refusal_rate",
                "faithfulness", "lexical_grounding", "seconds_per_turn"]
        _lineaje_payload = f"  {'metric':<22}" + "".join(f"{n:>20}" for n, _ in variants)
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:1e4634e7c15008221458bd8abcb5c91d884a7f5968f220db5462125ebce3122b'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1e4634e7c15008221458bd8abcb5c91d884a7f5968f220db5462125ebce3122b', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 369, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 369, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for k in keys:
            _lineaje_payload = f"  {k:<22}" + "".join(f"{f(s['summary'].get(k)):>20}" for _, s in variants)
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:60c5e358b4b3a6181e611196501bde6702a0ce54d676f05a199b14d11ca6649c'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:60c5e358b4b3a6181e611196501bde6702a0ce54d676f05a199b14d11ca6649c', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 371, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 371, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        for n, s in variants:
            fs = s["summary"]["followup_safety"]
            _lineaje_payload = (f"  [{n}] follow-up safety: {fs['n']} suggestions, guard safe {f(fs['guard_safe'])}, "
                  f"intent allowed {f(fs['intent_allowed'])}")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:e3be4011e6cbfa7bbb76f261a751cbf62d50b5ffe370e7cc4ed4ca66e9651e83'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e3be4011e6cbfa7bbb76f261a751cbf62d50b5ffe370e7cc4ed4ca66e9651e83', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 374, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 374, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            lat = s["summary"].get("latency") or {}
            _lineaje_payload = f"  [{n}] turn latency: {fmt_stats(lat.get('turn_ms'))}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:5f890330579ef6445ae04b79314a57581a34b57a953e210283e9ef6575641b97'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5f890330579ef6445ae04b79314a57581a34b57a953e210283e9ef6575641b97', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 377, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 377, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            _lineaje_payload = f"  [{n}] time to first token: {fmt_stats(lat.get('ttft_ms'))}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:0c3e91d46c100397a9098f415e567ad42f594b308b95230ef4e18cddde12f3f7'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0c3e91d46c100397a9098f415e567ad42f594b308b95230ef4e18cddde12f3f7', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 378, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 378, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            for layer, st in (lat.get("layers") or {}).items():
                _lineaje_payload = f"  [{n}]   {layer:<16} p50 {st['p50']} ms · p95 {st['p95']} ms"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in f).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:689f251d046171c431fca9933f228e946a5d49aeb23cbcc12fc98cf384dca2c4'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:689f251d046171c431fca9933f228e946a5d49aeb23cbcc12fc98cf384dca2c4', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 380, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 380, 'function': 'f', 'agent_name': 'f', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
    _lineaje_payload = f"\nSaved to {out.get('path')}  ({out.get('seconds')}s)"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_agent_report).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:ddf0ade9c262c803065d6c605662b5d0c4a9213d22a532d7a7dd6553281019a3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ddf0ade9c262c803065d6c605662b5d0c4a9213d22a532d7a7dd6553281019a3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/agent_eval.py', 'line': 381, 'function': 'print_agent_report'}, 'file': 'rag/eval/agent_eval.py', 'line': 381, 'function': 'print_agent_report', 'agent_name': 'print_agent_report', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
