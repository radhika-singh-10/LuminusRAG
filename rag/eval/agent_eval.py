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
        base = _source_ranks(get_retriever().invoke(it["question"]), it["expected_source"], config.TOP_K)
        pers = _source_ranks(PersonalizedRetriever(interests=profile, k=config.TOP_K,
                                                   graph_k=config.GRAPH_K).invoke(it["question"]),
                             it["expected_source"], config.TOP_K)
        rows.append({"id": it["id"], "persona": it["persona"], "question": it["question"],
                     "expected": it["expected_source"], "interests": [p["name"] for p in profile[:4]],
                     "baseline": base, "personalized": pers})
        if verbose:
            print(f"  {it['id']} {it['persona']:<11} {it['question'][:40]:<40} "
                  f"base@1={base['hit@1']:.0f} pers@1={pers['hit@1']:.0f}  ({', '.join(p['name'] for p in profile[:3])})")
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
                print(f"    step {r['step']:>2} [{r.get('origin')}] {question[:70]}"
                      f"  -> {len(r['followups'])} follow-ups")
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
        sv = np.asarray(emb.embed_documents(sugg))
        own_sim = sv @ own
        other_sim = np.stack([sv @ o for o in others], axis=1)
        align = list(own_sim - other_sim.mean(axis=1))
        nearest = list((own_sim > other_sim.max(axis=1)).astype(float))
    novelty, dupes = [], []
    for i, t in enumerate(turns):
        if i == 0:
            continue
        prev = np.asarray(emb.embed_documents([x["question"] for x in turns[:i]]))
        sim = float((prev @ np.asarray(emb.embed_query(t["question"]))).max())
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
            print(f"  session {spec['id']} ({spec['persona']})")
        sessions.append(run_session(agent, spec, personas, steps, verbose))
    keys = ["steps", "followups_per_turn", "turns_with_followups", "followup_taken_rate",
            "followup_answered", "followup_local", "novelty", "duplicate_rate",
            "persona_alignment", "on_persona", "refusal_rate", "lexical_grounding", "seconds_per_turn"]
    summary = {k: _mean(s[k] for s in sessions) for k in keys}
    summary["max_followups"] = max(s["max_followups"] for s in sessions)
    summary["limit_enforced"] = _mean(float(s["limit_enforced"]) for s in sessions)
    summary["final_summary"] = _mean(float(s["final_summary"]) for s in sessions)
    if verbose:
        print("  checking follow-up safety and answer faithfulness…")
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
            print("Personalized retrieval:")
        out["retrieval"] = eval_personalized_retrieval(verbose=verbose)
        out["regression"] = eval_profile_regression()
    if sessions:
        if verbose:
            print("Sessions (personalized):")
        out["sessions"] = eval_sessions(steps=steps, limit=limit, verbose=verbose)
        if compare:
            if verbose:
                print("Sessions (personalization off):")
            with overrides({"PERSONALIZE": False}):
                out["sessions_baseline"] = eval_sessions(steps=steps, limit=limit, verbose=verbose)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    path = config.EVAL_RESULTS_DIR / f"agent-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))
    out["path"] = str(path)
    return out


def print_agent_report(out: dict) -> None:
    def f(v):
        return "n/a" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)

    if r := out.get("retrieval"):
        print(f"\nPersonalized retrieval ({r['n']} ambiguous questions, expected source file)")
        print(f"  {'':<14}{'hit@1':>8}{'hit@3':>8}{'MRR':>8}{'share':>8}")
        for v in ("baseline", "personalized"):
            print(f"  {v:<14}" + "".join(f"{f(r[v][m]):>8}" for m in ("hit@1", "hit@3", "mrr", "source_share")))
    if g := out.get("regression"):
        print(f"\nRegression check ({g['n']} normal questions, profile from unrelated history)")
        for k, v in g.items():
            if k != "n":
                print(f"  {k:<20} recall {f(v['recall'])}  MRR {f(v['mrr'])}")
    variants = [("personalized", out.get("sessions")), ("no personalization", out.get("sessions_baseline"))]
    variants = [(n, s) for n, s in variants if s]
    if variants:
        print("\nMulti-step sessions")
        keys = ["steps", "limit_enforced", "final_summary", "followups_per_turn", "max_followups",
                "turns_with_followups", "followup_taken_rate", "followup_answered", "followup_local",
                "novelty", "duplicate_rate", "persona_alignment", "on_persona", "refusal_rate",
                "faithfulness", "lexical_grounding", "seconds_per_turn"]
        print(f"  {'metric':<22}" + "".join(f"{n:>20}" for n, _ in variants))
        for k in keys:
            print(f"  {k:<22}" + "".join(f"{f(s['summary'].get(k)):>20}" for _, s in variants))
        for n, s in variants:
            fs = s["summary"]["followup_safety"]
            print(f"  [{n}] follow-up safety: {fs['n']} suggestions, guard safe {f(fs['guard_safe'])}, "
                  f"intent allowed {f(fs['intent_allowed'])}")
            lat = s["summary"].get("latency") or {}
            print(f"  [{n}] turn latency: {fmt_stats(lat.get('turn_ms'))}")
            print(f"  [{n}] time to first token: {fmt_stats(lat.get('ttft_ms'))}")
            for layer, st in (lat.get("layers") or {}).items():
                print(f"  [{n}]   {layer:<16} p50 {st['p50']} ms · p95 {st['p95']} ms")
    print(f"\nSaved to {out.get('path')}  ({out.get('seconds')}s)")
