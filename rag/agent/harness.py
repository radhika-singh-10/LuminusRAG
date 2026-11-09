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
    trace_id: str


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
    # LINEAJE: runtime guardrail checks `args` as it flows from the agent to a tool, after the tool returns (in _call).
    #   Detected: this statement moves data from the agent to a tool with no runtime policy check (detection confidence: medium).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `args` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:29ba6c5a4c0a63eb3388bcce11e9508a4727fdac73b4857e8307867507666328'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:29ba6c5a4c0a63eb3388bcce11e9508a4727fdac73b4857e8307867507666328', phase='post_tool', boundary={'source': 'tool_result', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='agent', destination_type='tool', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness'}, 'invocation': {'file': 'rag/agent/harness.py', 'line': 94, 'function': '_call'}, 'file': 'rag/agent/harness.py', 'line': 94, 'function': '_call', 'agent_name': '_call', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        args = _gr_client.enforce(_gr_site, args, content_type='application/json', variable_name='args', source_file=__file__, before_line=94)
    except _gr_client.GuardrailUnavailableError:
        pass
    out = tool.invoke(args)
    entry = {"layer": layer, "tool": tool.name, "ms": round((time.perf_counter() - t0) * 1000)}
    if note:
        entry["note"] = note(out)
    return out, entry


class AgentHarness:
    """Multi-step conversational RAG agent. One instance can serve many chats."""

    def __init__(self, llm=None, max_steps: int | None = None, user_id: str = "local"):
        from ..chain import GuardedPipeline

        # LINEAJE: runtime guardrail checks `llm` as it flows from the agent to the LLM, before it is sent to the model (in AgentHarness.__init__).
        #   Detected: this statement moves data from the agent to the LLM with no runtime policy check (detection confidence: medium).
        #   Decision: the Guardrail evaluates AI_AGENT_ACTIVITY_LOG, AI_APP_SEC_006, AI_APP_SEC_028, AI_APP_SEC_070 (+2 more); sensitive values in `llm` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9e9fee262f0b56b9b44d00dde7d6bbdc3c05e99af3720c05925bcc4d495b0a6c'
        _gr_client = _lineaje_load_gr_client()
        _lineaje_interaction_id = _gr_client.new_interaction_id()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9e9fee262f0b56b9b44d00dde7d6bbdc3c05e99af3720c05925bcc4d495b0a6c', phase='pre_model', boundary={'source': 'agent_message', 'sink': 'model'}, fail_mode='BLOCK', source_type='agent', destination_type='llm', components={'source': {'entity_type': 'agent', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV'}, 'invocation': {'file': 'rag/agent/harness.py', 'function': 'AgentHarness.__init__', 'line': 107}, 'destination': {'entity_type': 'llm', 'name': 'Qwen2.5-1.5B-Instruct', 'provider': 'qwen', 'version': ''}, 'file': 'rag/agent/harness.py', 'line': 107, 'function': '__init__', 'agent_name': 'AgentHarness', 'agent_name_source': 'inferred_from_class', 'boundary_id': 'bnd:7123e3cc2e20e33e'}, interaction_id=_lineaje_interaction_id)
        try:
            llm = _gr_client.enforce(_gr_site, llm, content_type='application/json', variable_name='llm', source_file=__file__, before_line=107)
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            raise
        self.pipeline = GuardedPipeline(llm)
        # LINEAJE: runtime guardrail checks `self.pipeline` as it flows from the LLM to the agent, after the model replies (in AgentHarness.__init__).
        #   Detected: this statement moves data from the LLM to the agent with no runtime policy check (detection confidence: medium).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_011, AI_DAT_SEC_025, AI_DAT_SEC_027, AI_DAT_SEC_029; sensitive values in `self.pipeline` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:6a9234ba123d9975d9b57f783c472e9a3f60e068a3072b5629923d4b6b9b83ca'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:6a9234ba123d9975d9b57f783c472e9a3f60e068a3072b5629923d4b6b9b83ca', phase='post_model', boundary={'source': 'model', 'sink': 'agent_message'}, fail_mode='BLOCK', source_type='llm', destination_type='agent', components={'source': {'entity_type': 'agent', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV'}, 'invocation': {'file': 'rag/agent/harness.py', 'function': 'AgentHarness.__init__', 'line': 107}, 'destination': {'entity_type': 'llm', 'name': 'Qwen2.5-1.5B-Instruct', 'provider': 'qwen', 'version': ''}, 'file': 'rag/agent/harness.py', 'line': 107, 'function': '__init__', 'agent_name': 'AgentHarness', 'agent_name_source': 'inferred_from_class', 'boundary_id': 'bnd:7123e3cc2e20e33e'}, interaction_id=locals().get('_lineaje_interaction_id'))
        try:
            self.pipeline = _gr_client.enforce(_gr_site, self.pipeline, content_type='application/json', variable_name='self.pipeline', source_file=__file__, before_line=107)
        except _gr_client.GuardrailUnavailableError:
            pass
        self.max_steps = max_steps or config.AGENT_MAX_STEPS
        self.user_id = user_id
        self.graph = self._build()

    # ----- public API -----

    def events(self, chat_id: str, question: str, from_followup: bool = False):
        """Yield {"type": "status"|"token"|"final", ...} for one user turn."""
        from ..observability import trace_config

        # One trace per turn: this run is the root, every node / tool / retriever /
        # LLM call below it is a child span (LangChain callbacks).
        cfg = trace_config("agent_turn", metadata={"chat_id": chat_id, "user_id": self.user_id,
                                                   "from_followup": from_followup},
                           tags=["agent"])
        state = {"chat_id": chat_id, "user_id": self.user_id, "raw_question": question,
                 "from_followup": from_followup, "trace": [], "trace_id": str(cfg["run_id"])}
        final = None
        for mode, chunk in self.graph.stream(state, cfg, stream_mode=["custom", "values"]):
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
        # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in AgentHarness._memory).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:27d174a0735d9cb9ee1271df49b94cb50078a30b047137953eb26609dad0903a'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:27d174a0735d9cb9ee1271df49b94cb50078a30b047137953eb26609dad0903a', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness'}, 'invocation': {'file': 'rag/agent/harness.py', 'line': 175, 'function': 'AgentHarness._memory'}, 'file': 'rag/agent/harness.py', 'line': 175, 'function': '_memory', 'agent_name': 'AgentHarness', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
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
        recent = [m["content"] for m in s["messages"] if m["role"] == "user"]
        intent, tr = _call("safety", T.intent_check, {"question": s["question"], "recent": recent},
                           lambda i: i.category)
        if not intent.allowed:
            return {**self._blocked(s["question"], intent.message, intent, s["guard"], s.get("pii", [])),
                    "intent": intent, "trace": [tr]}
        return {"intent": intent, "trace": [tr]}

    def _retrieve(self, s: AgentState) -> dict:
        _status("retrieve", "Searching your documents (personalized)…" if s.get("interests")
                else "Searching your documents…")
        try:
            _lineaje_obs = _lineaje_load_gr_client()
            _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:2e32a8bd791a2f87c88cf9fb3872edf72e189142a630d135d335475d36755e7d', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/agent/harness.py', 'line': 234, 'function': '_retrieve', 'agent_name': 'AgentHarness', 'agent_name_source': 'inferred_from_class', 'call_target': '_call', 'source': {'entity_type': 'agent', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV'}, 'invocation': {'file': 'rag/agent/harness.py', 'function': 'AgentHarness._retrieve', 'line': 234}, 'destination': {'entity_type': 'rag', 'file_path': 'rag/agent/personalize.py', 'line': 147, 'name': 'PersonalizedRetriever', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV'}, 'boundary_id': 'bnd:e6fe19dc86a1c9ec'}, observe_only=True)
            _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
        except Exception as _lineaje_obs_err:
            [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
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
                       "sources": sources, "followups": s.get("followups") or [],
                       "trace_id": s.get("trace_id")})
        trace = [tr]
        if s.get("summary") is not None:
            save_session(s["chat_id"], s["user_id"], summary=s["summary"],
                         summary_step=s.get("summary_step") or 0)
        if closed:  # final summary of the whole chat, cached with the chat
            from ..history import summarize_chat

            _status("summarize", "Conversation complete. Summarizing it…")
            t0 = time.perf_counter()
            try:
                _lineaje_payload = s["chat_id"]
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the LLM, before it is sent to the model (in AgentHarness._save).
                #   Detected: this statement moves data from the agent to the LLM with no runtime policy check (detection confidence: medium).
                #   Decision: the Guardrail evaluates AI_AGENT_ACTIVITY_LOG, AI_APP_SEC_006, AI_APP_SEC_028, AI_APP_SEC_070 (+2 more); sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:f09911965f5e2af588c2a68ff5f608aa8e82b0c7d321f22930a20e8aebead877'
                _gr_client = _lineaje_load_gr_client()
                _lineaje_interaction_id = _gr_client.new_interaction_id()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:f09911965f5e2af588c2a68ff5f608aa8e82b0c7d321f22930a20e8aebead877', phase='pre_model', boundary={'source': 'agent_message', 'sink': 'model'}, fail_mode='BLOCK', source_type='agent', destination_type='llm', components={'source': {'entity_type': 'agent', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV'}, 'invocation': {'file': 'rag/agent/harness.py', 'function': 'AgentHarness._save', 'line': 319}, 'destination': {'entity_type': 'llm', 'name': 'llama3.2:3b', 'provider': 'meta', 'version': ''}, 'file': 'rag/agent/harness.py', 'line': 319, 'function': '_save', 'agent_name': 'AgentHarness', 'agent_name_source': 'inferred_from_class', 'boundary_id': 'bnd:1c3b4c6f7130dc18'}, interaction_id=_lineaje_interaction_id)
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=319)
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    raise
                final = summarize_chat(_lineaje_payload, T._ollama(), force=True)
                # LINEAJE: runtime guardrail checks `final` as it flows from the LLM to the agent, after the model replies (in AgentHarness._save).
                #   Detected: this statement moves data from the LLM to the agent with no runtime policy check (detection confidence: medium).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_011, AI_DAT_SEC_025, AI_DAT_SEC_027, AI_DAT_SEC_029; sensitive values in `final` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:274358f77ae1a4034145d6da514330c81db9272f8d624bbe9a6440e214cf6b20'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:274358f77ae1a4034145d6da514330c81db9272f8d624bbe9a6440e214cf6b20', phase='post_model', boundary={'source': 'model', 'sink': 'agent_message'}, fail_mode='BLOCK', source_type='llm', destination_type='agent', components={'source': {'entity_type': 'agent', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV'}, 'invocation': {'file': 'rag/agent/harness.py', 'function': 'AgentHarness._save', 'line': 319}, 'destination': {'entity_type': 'llm', 'name': 'llama3.2:3b', 'provider': 'meta', 'version': ''}, 'file': 'rag/agent/harness.py', 'line': 319, 'function': '_save', 'agent_name': 'AgentHarness', 'agent_name_source': 'inferred_from_class', 'boundary_id': 'bnd:1c3b4c6f7130dc18'}, interaction_id=locals().get('_lineaje_interaction_id'))
                try:
                    final = _gr_client.enforce(_gr_site, final, content_type='application/json', variable_name='final', source_file=__file__, before_line=319)
                except _gr_client.GuardrailUnavailableError:
                    pass
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
            "trace_id": s.get("trace_id"),
        })
        # LINEAJE: runtime guardrail checks `r` as it flows from the agent to the user interface, before it leaves the application (in AgentHarness._result).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `r` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:0dd6d983e22ad589f26758b0dd7dc40fee21c9e6898c88e9e56512e4c000ab39'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0dd6d983e22ad589f26758b0dd7dc40fee21c9e6898c88e9e56512e4c000ab39', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_ktrjIg0SaG9uMcsV', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness'}, 'invocation': {'file': 'rag/agent/harness.py', 'line': 343, 'function': 'AgentHarness._result'}, 'file': 'rag/agent/harness.py', 'line': 343, 'function': '_result', 'agent_name': 'AgentHarness', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            r = _gr_client.enforce(_gr_site, r, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        return r


def build_agent(llm=None, max_steps: int | None = None, user_id: str = "local") -> AgentHarness:
    return AgentHarness(llm, max_steps, user_id)
