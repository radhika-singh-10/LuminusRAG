"""Agent harness: a LangGraph state machine whose nodes are the layer tools.

    memory -> safety -> context -> intent -> retrieve -> answer -> personalize
           -> followups -> summarize -> evaluate -> save

- memory      recall_memory: messages, step count, rolling summary, interests.
              A chat holds at most AGENT_MAX_STEPS questions; after that the
              harness refuses further questions and asks for a new chat.
- safety      safety_check on the raw question (injection + PII policies).
              Unsafe -> refusal, saved and counted as a step.
- context     build_context (recent turns + rolling summary + interests), then
              contextualize rewrites follow-ups. The rewrite is model output,
              so it must pass the regex policy rules too.
- intent      intent_check: only AI questions continue.
- retrieve    personalized GraphRAG retrieval (ANN + personalized PageRank).
- answer      streamed, sanitized answer; web fallback (and storage) when the
              store can't answer (GuardedPipeline.answer_events).
- personalize update_interests from the answered question.
- followups   up to AGENT_MAX_FOLLOWUPS suggestions; none on the last step.
- summarize   rolling summary every SUMMARY_EVERY steps once older turns
              fall out of the recent window; a final chat summary when the
              step limit closes the chat.
- evaluate    evaluate_turn: online quality signals.
- save        save_turn: messages (PII-redacted), follow-ups, step count.

Every tool call is traced (layer, tool, milliseconds, short note). Events
stream through LangGraph's custom stream: status, token, and a final result.
"""
import operator
import time
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .. import config
from . import tools as T

LIMIT_MESSAGE = ("This conversation reached its limit of {n} questions. "
                 "Start a new chat to keep going; your interests carry over.")


class AgentState(TypedDict, total=False):
    chat_id: str
    user_id: str
    raw_question: str
    from_followup: bool
    step: int
    closed: bool
    messages: list[dict]
    summary: str | None
    summary_step: int
    interests: list[dict]
    context: dict
    question: str
    standalone: str | None
    guard: Any
    intent: Any
    pii: list[str]
    blocked: bool
    docs: list
    result: dict
    followups: list[dict]
    metrics: dict
    trace: Annotated[list[dict], operator.add]


def _label(meta: dict) -> str:
    if meta.get("origin") == "graph":
        return "🕸 Knowledge graph facts"
    if meta.get("origin") == "web":
        return f"🌐 {meta.get('title') or meta.get('source')} ({meta.get('source')})"
    name = Path(meta.get("source", "unknown")).name
    page = meta.get("page")
    return f"{name}, page {page + 1}" if page is not None else name


def _emit(event: dict) -> None:
    try:
        get_stream_writer()(event)
    except Exception:  # not running under .stream()
        pass


def _status(stage: str, message: str) -> None:
    _emit({"type": "status", "stage": stage, "message": message})


def _call(layer: str, tool, args: dict, note=None):
    """Invoke a layer tool and return (output, trace entry)."""
    t0 = time.perf_counter()
    out = tool.invoke(args)
    entry = {"layer": layer, "tool": tool.name, "ms": round((time.perf_counter() - t0) * 1000)}
    if note:
        entry["note"] = note(out)
    return out, entry


class AgentHarness:
    """Multi-step conversational RAG agent. One instance can serve many chats."""

    def __init__(self, llm=None, max_steps: int | None = None, user_id: str = "local"):
        from ..chain import GuardedPipeline

        self.pipeline = GuardedPipeline(llm)
        self.max_steps = max_steps or config.AGENT_MAX_STEPS
        self.user_id = user_id
        self.graph = self._build()

    # ----- public API -----

    def events(self, chat_id: str, question: str, from_followup: bool = False):
        """Yield {"type": "status"|"token"|"final", ...} for one user turn."""
        state = {"chat_id": chat_id, "user_id": self.user_id, "raw_question": question,
                 "from_followup": from_followup, "trace": []}
        final = None
        for mode, chunk in self.graph.stream(state, stream_mode=["custom", "values"]):
            if mode == "custom":
                yield chunk
            else:
                final = chunk
        yield {"type": "final", "result": self._result(final)}

    def turn(self, chat_id: str, question: str, from_followup: bool = False) -> dict:
        for e in self.events(chat_id, question, from_followup):
            if e["type"] == "final":
                return e["result"]
        raise RuntimeError("harness ended without a result")

    # ----- graph -----

    def _build(self):
        g = StateGraph(AgentState)
        for name in ("memory", "safety", "context", "intent", "retrieve", "answer",
                     "personalize", "followups", "summarize", "evaluate", "save"):
            g.add_node(name, getattr(self, f"_{name}"))
        g.add_edge(START, "memory")
        g.add_conditional_edges("memory", lambda s: END if s.get("closed") else "safety")
        g.add_conditional_edges("safety", lambda s: "save" if s.get("blocked") else "context")
        g.add_edge("context", "intent")
        g.add_conditional_edges("intent", lambda s: "save" if s.get("blocked") else "retrieve")
        g.add_edge("retrieve", "answer")
        g.add_edge("answer", "personalize")
        g.add_edge("personalize", "followups")
        g.add_edge("followups", "summarize")
        g.add_edge("summarize", "evaluate")
        g.add_edge("evaluate", "save")
        g.add_edge("save", END)
        return g.compile()

    def _memory(self, s: AgentState) -> dict:
        mem, tr = _call("memory", T.recall_memory, {"chat_id": s["chat_id"], "user_id": s["user_id"]},
                        lambda m: f"{len(m['messages']) // 2} earlier turns, "
                                  f"{len(m['interests'])} interests")
        session = mem["session"]
        step = session["steps"] + 1
        out = {"messages": mem["messages"], "summary": session.get("summary"),
               "summary_step": session.get("summary_step") or 0,
               "interests": mem["interests"], "step": step, "trace": [tr]}
        if session.get("closed") or session["steps"] >= self.max_steps:
            msg = LIMIT_MESSAGE.format(n=self.max_steps)
            _emit({"type": "token", "text": msg})
            out.update(closed=True, step=session["steps"], blocked=True, followups=[],
                       result={"question": s["raw_question"], "context": [], "answer": msg,
                               "origin": None, "limit_reached": True})
        return out

    def _blocked(self, question: str, message: str, intent, guard, pii) -> dict:
        _emit({"type": "token", "text": message})
        return {"blocked": True, "followups": [],
                "result": {"question": question, "context": [], "answer": message, "intent": intent,
                           "origin": None, "local_score": None, "pii_redacted": pii, "stored": 0,
                           "guard": guard, "output_actions": []}}

    def _safety(self, s: AgentState) -> dict:
        from ..intent import Intent
        from ..safety import strip_redactions

        _status("guard", "Checking safety policies…")
        guard, tr = _call("safety", T.safety_check, {"text": s["raw_question"]},
                          lambda g: "safe" if g.safe else f"blocked {g.rule_id} ({g.source})")
        if not guard.safe:
            category = "guard_error" if guard.source == "error" else "blocked_policy"
            q = strip_redactions(guard.text) if guard.text else "[question withheld]"
            return {**self._blocked(q, guard.message, Intent(category, False, guard.message, guard.reason),
                                    guard, []), "guard": guard, "question": q, "trace": [tr]}
        question = strip_redactions(guard.text) if guard.redacted else guard.text
        return {"guard": guard, "pii": guard.redacted, "question": question, "trace": [tr]}

    def _context(self, s: AgentState) -> dict:
        from ..policy import check_query

        ctx, tr1 = _call("context", T.build_context,
                         {"messages": s["messages"], "summary": s.get("summary"),
                          "interests": s.get("interests")},
                         lambda c: f"{len(c['recent']) // 2} recent turns"
                                   f"{', summary' if c['summary'] else ''}")
        trace, question, standalone = [tr1], s["question"], None
        if ctx["recent"]:
            _status("followup", "Reading the conversation…")
            rewritten, tr2 = _call("context", T.contextualize,
                                   {"question": question, "recent": ctx["recent"],
                                    "summary": ctx["summary"]},
                                   lambda r: "rewritten" if r != question else "unchanged")
            trace.append(tr2)
            if rewritten != question and check_query(rewritten, use_llm=False).safe:
                standalone = question = rewritten
        return {"context": ctx, "question": question, "standalone": standalone, "trace": trace}

    def _intent(self, s: AgentState) -> dict:
        if not config.INTENT_ENABLED:
            return {"intent": None}
        _status("intent", "Checking the question is about AI…")
        intent, tr = _call("safety", T.intent_check, {"question": s["question"]},
                           lambda i: i.category)
        if not intent.allowed:
            return {**self._blocked(s["question"], intent.message, intent, s["guard"], s.get("pii", [])),
                    "intent": intent, "trace": [tr]}
        return {"intent": intent, "trace": [tr]}

    def _retrieve(self, s: AgentState) -> dict:
        _status("retrieve", "Searching your documents (personalized)…" if s.get("interests")
                else "Searching your documents…")
        docs, tr = _call("retrieval", T.retrieve,
                         {"question": s["question"], "interests": s.get("interests")},
                         lambda d: f"{len(d)} passages")
        return {"docs": docs, "trace": [tr]}

    def _answer(self, s: AgentState) -> dict:
        t0 = time.perf_counter()
        base = {"intent": s.get("intent"), "pii_redacted": s.get("pii", []), "guard": s.get("guard"),
                "standalone_question": s.get("standalone")}
        result = None
        for e in self.pipeline.answer_events(s["docs"], s["question"], base):
            if e["type"] == "final":
                result = e["result"]
            else:
                _emit(e)
        tr = {"layer": "generation", "tool": T.generate_answer.name,
              "ms": round((time.perf_counter() - t0) * 1000), "note": f"origin {result['origin']}"}
        return {"result": result, "trace": [tr]}

    def _personalize(self, s: AgentState) -> dict:
        from ..eval.metrics import is_refusal

        r = s["result"]
        if not config.PERSONALIZE or r["origin"] == "none" or is_refusal(r["answer"]):
            return {}
        _status("personalize", "Updating your interests…")
        interests, tr = _call("personalization", T.update_interests,
                              {"user_id": s["user_id"], "chat_id": s["chat_id"],
                               "question": s["question"], "docs": r["context"]},
                              lambda i: ", ".join(x["name"] for x in i[:3]) or "none")
        return {"interests": interests, "trace": [tr]}

    def _followups(self, s: AgentState) -> dict:
        r = s["result"]
        if s["step"] >= self.max_steps or r["origin"] == "none":
            return {"followups": []}
        _status("followups", "Suggesting follow-up questions…")
        asked = s["context"]["asked"] + [s["raw_question"]]
        fu, tr = _call("followups", T.suggest_followups,
                       {"question": s["question"], "answer": r["answer"], "docs": r["context"],
                        "interests": s.get("interests"), "asked": asked},
                       lambda f: f"{len(f)} suggestions")
        return {"followups": fu, "trace": [tr]}

    def _summarize(self, s: AgentState) -> dict:
        due = (len(s["messages"]) // 2 >= config.HISTORY_TURNS
               and s["step"] - (s.get("summary_step") or 0) >= config.SUMMARY_EVERY)
        if not due:
            return {}
        _status("summarize", "Summarizing earlier turns…")
        summary, tr = _call("summarization", T.summarize_session,
                            {"messages": s["messages"], "previous": s.get("summary")},
                            lambda x: f"{len(x or '')} chars")
        return {"summary": summary, "summary_step": s["step"], "trace": [tr]}

    def _evaluate(self, s: AgentState) -> dict:
        r = s["result"]
        metrics, tr = _call("eval", T.evaluate_turn,
                            {"question": s["question"], "answer": r["answer"], "docs": r["context"],
                             "local_score": r.get("local_score"), "followups": s.get("followups")},
                            lambda m: f"grounding {m['lexical_grounding']:.2f}"
                            if m.get("lexical_grounding") is not None else "n/a")
        return {"metrics": metrics, "trace": [tr]}

    def _save(self, s: AgentState) -> dict:
        from .memory import save_session

        r = s["result"]
        closed = s["step"] >= self.max_steps
        sources = [{"label": _label(d.metadata), "text": d.page_content} for d in r["context"]]
        _, tr = _call("memory", T.save_turn,
                      {"chat_id": s["chat_id"], "user_id": s["user_id"], "question": r["question"],
                       "answer": r["answer"], "step": s["step"], "closed": closed,
                       "sources": sources, "followups": s.get("followups") or []})
        trace = [tr]
        if s.get("summary") is not None:
            save_session(s["chat_id"], s["user_id"], summary=s["summary"],
                         summary_step=s.get("summary_step") or 0)
        if closed:  # final summary of the whole chat, cached with the chat
            from ..history import summarize_chat

            _status("summarize", "Conversation complete. Summarizing it…")
            t0 = time.perf_counter()
            try:
                final = summarize_chat(s["chat_id"], T._ollama(), force=True)
            except Exception:
                final = None
            trace.append({"layer": "summarization", "tool": "summarize_chat",
                          "ms": round((time.perf_counter() - t0) * 1000)})
            return {"closed": True, "summary": final or s.get("summary"), "trace": trace}
        return {"trace": trace}

    # ----- result -----

    def _result(self, s: dict) -> dict:
        r = dict(s.get("result") or {})
        r.setdefault("context", [])
        r.update({
            "step": s.get("step"), "max_steps": self.max_steps,
            "closed": bool(s.get("closed")) or (s.get("step") or 0) >= self.max_steps,
            "followups": s.get("followups") or [],
            "interests": s.get("interests") or [],
            "summary": s.get("summary"),
            "metrics": s.get("metrics") or {},
            "trace": s.get("trace") or [],
            "from_followup": s.get("from_followup", False),
        })
        return r


def build_agent(llm=None, max_steps: int | None = None, user_id: str = "local") -> AgentHarness:
    return AgentHarness(llm, max_steps, user_id)
