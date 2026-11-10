"""Every layer of the agent harness as a LangChain tool.

Each tool is a typed StructuredTool (name, description, argument schema), so
the layers can be called by the harness, inspected, tested on their own, or
handed to a tool-calling agent. The harness (rag/agent/harness.py) calls
them in a fixed order: safety must run before anything sees the question, so
the order is not left to a model.

Layer           Tool                 Does
--------------  -------------------  --------------------------------------------
memory          recall_memory        chat messages, session (steps, rolling summary), interests
safety          safety_check         policy guard: prompt injection + PII (regex + LLM judge)
context         build_context        recent turns + rolling summary + interests, within budget
context         contextualize        rewrite a follow-up into a standalone question
safety          intent_check         only AI questions; action requests refused
retrieval       retrieve             personalized GraphRAG retrieval (ANN + personalized PageRank)
generation      generate_answer      answer from the passages (the harness streams it instead)
personalization update_interests     learn interests from the answered question
followups       suggest_followups    up to 3 grounded, novel, safe follow-up questions
summarization   summarize_session    rolling summary of turns older than the recent window
eval            evaluate_turn        online quality signals for one turn
memory          save_turn            persist the exchange (PII-redacted) and session state
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

from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.tools import tool

from .. import config


@lru_cache(maxsize=1)
def _ollama():
    from ..prompt_cache import chat_ollama

    return chat_ollama(config.AGENT_MODEL, temperature=0, num_predict=300)


# ---------- memory ----------

@tool
def recall_memory(chat_id: str, user_id: str = "local") -> dict:
    """Load the chat's messages, its session state (step count, rolling summary,
    closed flag) and the user's interest profile."""
    from ..history import load_messages
    from .memory import get_interests, get_session

    return {"messages": load_messages(chat_id),
            "session": get_session(chat_id, user_id),
            "interests": get_interests(user_id, chat_id) if config.PERSONALIZE else []}


@tool
def save_turn(chat_id: str, user_id: str, question: str, answer: str, step: int,
              closed: bool, meta: str = "", sources: list[dict] | None = None,
              followups: list[dict] | None = None, trace_id: str | None = None) -> dict:
    """Persist one exchange (question already PII-redacted) and the session's step
    count. trace_id links the saved answer to its trace (observability)."""
    from ..history import add_exchange
    from .memory import save_session

    add_exchange(chat_id, question, answer, meta, sources,
                 extra={"followups": followups or [], "step": step, "trace_id": trace_id})
    save_session(chat_id, user_id, steps=step, closed=closed)
    return {"saved": True, "step": step, "closed": closed}


# ---------- safety ----------

@tool
def safety_check(text: str, use_llm: bool = True):
    """Check text against the prompt-injection and PII policies. Returns a
    GuardResult: safe flag, rule, and the PII-redacted text."""
    from ..policy import check_query

    return check_query(text, use_llm=use_llm)


@tool
def intent_check(question: str, recent: list[str] | None = None):
    """Classify the question's intent; only AI-related questions are allowed.
    `recent` (earlier questions in the chat) disambiguates terms like "guardrails"."""
    from ..intent import classify_intent

    return classify_intent(question, recent)


# ---------- context ----------

@tool
def build_context(messages: list[dict], summary: str | None = None,
                  interests: list[dict] | None = None, max_chars: int = 3000) -> dict:
    """Assemble the conversation context: the last HISTORY_TURNS exchanges, the
    rolling summary of older ones, the interest names, and every question asked
    so far (for follow-up novelty). Older text is trimmed first to fit max_chars."""
    recent = messages[-2 * config.HISTORY_TURNS:]
    while recent and sum(len(m["content"]) for m in recent) > max_chars:
        recent = recent[2:]
    return {
        "recent": recent,
        "summary": (summary or "")[:800] or None,
        "interests": [i["name"] for i in interests or []],
        "asked": [m["content"] for m in messages if m["role"] == "user"],
    }


@tool
def contextualize(question: str, recent: list[dict], summary: str | None = None) -> str:
    """Rewrite a follow-up ("what about its cost?") into a standalone question
    using the recent turns and rolling summary. Standalone questions pass through."""
    from ..followup import standalone_question

    return standalone_question(question, recent, summary)


# ---------- retrieval and generation ----------

@tool
def retrieve(question: str, interests: list[dict] | None = None) -> list[Document]:
    """Personalized GraphRAG retrieval: ANN vector search nudged toward the
    user's interests, reranked with personalized PageRank over the knowledge graph."""
    from .personalize import PersonalizedRetriever

    try:
        _lineaje_obs = _lineaje_load_gr_client()
        _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:6e07746434ee442157368aa171205745d157971c5df2f7fa8978d290d214f3f5', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/agent/tools.py', 'line': 124, 'function': 'retrieve', 'agent_name': 'retrieve', 'agent_name_source': 'inferred_from_function', 'call_target': 'PersonalizedRetriever(interests=interests or [], k=config.TOP_K, graph_k=config.', 'not_on_graph': True}, observe_only=True)
        _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
    except Exception as _lineaje_obs_err:
        [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
    return PersonalizedRetriever(interests=interests or [], k=config.TOP_K,
                                 graph_k=config.GRAPH_K).invoke(question)


@tool
def generate_answer(question: str, docs: list[Document]) -> str:
    """Answer the question from the passages, citing them as [n]. (The harness
    streams the answer through GuardedPipeline.answer_events instead.)"""
    try:
        _lineaje_obs = _lineaje_load_gr_client()
        _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:bf722f2b8a39aebd72bfbf3b7dc0d44ab2619ba66c386733443bca5bc3aa3b70', phase='', boundary={}, fail_mode='ALLOW', source_type='agent', destination_type='llm', components={'file': 'rag/agent/tools.py', 'line': 132, 'function': 'generate_answer', 'agent_name': 'generate_answer', 'agent_name_source': 'inferred_from_function', 'invocation': {'file': 'rag/agent/tools.py', 'function': 'generate_answer', 'line': 132}, 'destination': {'entity_type': 'llm', 'name': 'llama3.2:3b', 'provider': 'meta', 'version': ''}, 'source': {'entity_type': 'agent', 'file_path': 'rag/agent/harness.py', 'line': 101, 'name': 'AgentHarness', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_S54IqBD8FU6fX42P'}, 'boundary_id': 'bnd:f9092249cc89be7e'}, observe_only=True)
        _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'agent_to_llm'}, content_type='application/json')
    except Exception as _lineaje_obs_err:
        [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
    from ..chain import build_answer_chain, get_llm

    return build_answer_chain(get_llm()).invoke({"context": docs, "question": question})


# ---------- personalization ----------

@tool
def update_interests(user_id: str, chat_id: str, question: str, docs: list[Document]) -> list[dict]:
    """Learn from an answered question: decay old interests, add the graph
    entities in the question (and, weaker, in the answering chunks)."""
    from .memory import add_interests, get_interests
    from .personalize import interests_from_turn

    if config.PERSONALIZE:
        add_interests(user_id, chat_id, interests_from_turn(question, docs))
    return get_interests(user_id, chat_id) if config.PERSONALIZE else []


# ---------- follow-ups ----------

@tool
def suggest_followups(question: str, answer: str, docs: list[Document],
                      interests: list[dict] | None = None, asked: list[str] | None = None,
                      limit: int | None = None) -> list[dict]:
    """Up to AGENT_MAX_FOLLOWUPS follow-up questions: answerable from the store,
    not already asked, safe, and ranked toward the user's interests."""
    from .followups import suggest

    return suggest(question, answer, docs, interests or [], asked or [], limit)


# ---------- summarization ----------

@tool
def summarize_session(messages: list[dict], previous: str | None = None) -> str | None:
    """Rolling summary of the turns older than the recent window, so long chats
    keep their earlier context in a few lines. Refused questions are marked,
    never answered by the summarizer."""
    from ..history import summarize_messages

    older = messages[:-2 * config.HISTORY_TURNS]
    if len(older) < 2:
        # LINEAJE: runtime guardrail checks `previous` as it flows from a tool to the agent, after the tool returns (in summarize_session).
        #   Detected: this statement moves data from a tool to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `previous` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:1fe5f480a437c34980d9765a9af0a7f8ffae40cef37dc7280a30b0353a1747bc'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1fe5f480a437c34980d9765a9af0a7f8ffae40cef37dc7280a30b0353a1747bc', phase='post_tool', boundary={'source': 'tool_result', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='tool', destination_type='agent', components={'invocation': {'file': 'rag/agent/tools.py', 'line': 175, 'function': 'summarize_session'}, 'file': 'rag/agent/tools.py', 'line': 175, 'function': 'summarize_session', 'agent_name': 'summarize_session', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            previous = _gr_client.enforce(_gr_site, previous, content_type='application/json', variable_name='previous', source_file=__file__, before_line=175)
        except _gr_client.GuardrailUnavailableError:
            pass
        return previous
    try:
        return summarize_messages(older, _ollama())
    except Exception:  # Ollama unavailable: keep the previous summary
        # LINEAJE: runtime guardrail checks `previous` as it flows from a tool to the agent, after the tool returns (in summarize_session).
        #   Detected: this statement moves data from a tool to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `previous` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9172db6ae53d52ce1f114176ab018e9ce42474b30a7672108e06b769c5f30dc5'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9172db6ae53d52ce1f114176ab018e9ce42474b30a7672108e06b769c5f30dc5', phase='post_tool', boundary={'source': 'tool_result', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='tool', destination_type='agent', components={'invocation': {'file': 'rag/agent/tools.py', 'line': 179, 'function': 'summarize_session'}, 'file': 'rag/agent/tools.py', 'line': 179, 'function': 'summarize_session', 'agent_name': 'summarize_session', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            previous = _gr_client.enforce(_gr_site, previous, content_type='application/json', variable_name='previous', source_file=__file__, before_line=179)
        except _gr_client.GuardrailUnavailableError:
            pass
        return previous


# ---------- eval ----------

@tool
def evaluate_turn(question: str, answer: str, docs: list[Document],
                  local_score: float | None = None, followups: list[dict] | None = None) -> dict:
    """Online quality signals for one turn: retrieval score, refusal, citation
    validity, lexical grounding in the passages, follow-up count and
    answerability, and (AGENT_ONLINE_NLI) NLI faithfulness."""
    from ..eval.metrics import citation_metrics, is_refusal, tokens

    refused = is_refusal(answer)
    ctx = [d.page_content for d in docs]
    ctx_tokens = set(t for c in ctx for t in tokens(c))
    ans_tokens = [t for t in tokens(answer) if len(t) > 3]
    grounding = (sum(t in ctx_tokens for t in ans_tokens) / len(ans_tokens)) if ans_tokens else None
    out = {
        "retrieval_score": local_score,
        "refused": refused,
        **citation_metrics(answer, len(docs)),
        "lexical_grounding": grounding,
        "n_followups": len(followups or []),
        "followup_answerability": (sum(f["answerability"] for f in followups) / len(followups))
        if followups else None,
    }
    if config.AGENT_ONLINE_NLI and not refused and ctx:
        from ..eval.truthfulness import get_scorer

        out["faithfulness"] = get_scorer().faithfulness(answer, ctx)["faithfulness"]
    # LINEAJE: runtime guardrail checks `out` as it flows from a tool to the agent, after the tool returns (in evaluate_turn).
    #   Detected: this statement moves data from a tool to the agent with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `out` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:b37cba334ef6e38e558234efaddec597385d735c0fd45db1fde40a6b990a8242'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:b37cba334ef6e38e558234efaddec597385d735c0fd45db1fde40a6b990a8242', phase='post_tool', boundary={'source': 'tool_result', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='tool', destination_type='agent', components={'invocation': {'file': 'rag/agent/tools.py', 'line': 210, 'function': 'evaluate_turn'}, 'file': 'rag/agent/tools.py', 'line': 210, 'function': 'evaluate_turn', 'agent_name': 'evaluate_turn', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='application/json', variable_name='out', source_file=__file__, before_line=210)
    except _gr_client.GuardrailUnavailableError:
        pass
    return out


TOOLS = [recall_memory, safety_check, build_context, contextualize, intent_check, retrieve,
         generate_answer, update_interests, suggest_followups, summarize_session,
         evaluate_turn, save_turn]
