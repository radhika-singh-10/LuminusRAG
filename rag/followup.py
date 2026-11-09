"""History-aware retrieval: turn a follow-up into a standalone question.

"What is HNSW?" ... "What is its main cost?" -> "What is the main cost of HNSW?"

This is LangChain's history-aware retriever pattern (contextualize the
question with the chat history, then retrieve), with worked examples in the
prompt because the small local model otherwise returns follow-ups unchanged. The rewrite uses the local
Ollama model and runs only when the question looks like a follow-up
(pronouns, "what about ...", "the other ..."), so standalone questions
pass through unchanged. History messages are the stored, PII-redacted chat.
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

import re
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from . import config

CONTEXTUALIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You rewrite the user's latest question so it can be understood without the "
     "conversation. Replace pronouns such as it, its, they, this, or that with the "
     "thing they refer to in the conversation. Do NOT answer the question. If the "
     "question is already standalone, return it unchanged. Reply with the rewritten "
     "question only.\n\n"
     "Examples:\n"
     "Conversation: User: What is LoRA? / Assistant: LoRA is a parameter-efficient "
     "fine-tuning method.\n"
     "Latest question: How much memory does it save?\n"
     "Rewritten: How much memory does LoRA save?\n\n"
     "Conversation: User: Which vector databases exist? / Assistant: Chroma, FAISS "
     "and Qdrant.\n"
     "Latest question: What about pgvector?\n"
     "Rewritten: Is pgvector a vector database, and how does it compare to Chroma, "
     "FAISS and Qdrant?\n\n"
     "Conversation: User: What is RLHF? / Assistant: Reinforcement learning from "
     "human feedback.\n"
     "Latest question: What is a context window?\n"
     "Rewritten: What is a context window?"),
    ("human", "Conversation: {conversation}\nLatest question: {question}\nRewritten:"),
])

_FOLLOWUP = re.compile(
    r"\b(?:it|its|it's|they|them|their|this|that|these|those|he|she|his|her|the former|"
    r"the latter|the same|what about|how about|and what|also|instead|compared to that|"
    r"the other|another one|which one|the two|both|either|neither)\b", re.IGNORECASE)


def looks_like_followup(question: str) -> bool:
    return bool(_FOLLOWUP.search(question))


@lru_cache(maxsize=1)
def _contextualizer():
    from .prompt_cache import chat_ollama

    llm = chat_ollama(config.GUARD_MODEL, temperature=0, num_predict=80)
    return (CONTEXTUALIZE_PROMPT | llm | StrOutputParser()).with_config(run_name="followup_rewriter")


def to_messages(history: list[dict], turns: int | None = None) -> list:
    """UI/CLI history ({role, content}) -> the last `turns` Q&A pairs as LangChain messages."""
    turns = turns or config.HISTORY_TURNS
    msgs = [HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"][:600])
            for m in history if m.get("content")]
    return msgs[-turns * 2:]


def conversation_text(history: list[dict], turns: int | None = None) -> str:
    return " / ".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {' '.join(m.content.split())}"
        for m in to_messages(history, turns))


def standalone_question(question: str, history: list[dict] | None, summary: str | None = None) -> str:
    """Rewrite a follow-up using the history (and the rolling summary of older
    turns, if any); otherwise return the question as is."""
    if not (config.HISTORY_AWARE and history and looks_like_followup(question)):
        # LINEAJE: runtime guardrail checks `question` as it flows from the agent to the user interface, before it leaves the application (in standalone_question).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `question` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:295402fac3604c649d4a407768c171f9aecfba8dd5776a938e6b6a5eec002d87'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:295402fac3604c649d4a407768c171f9aecfba8dd5776a938e6b6a5eec002d87', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_m2lqBnC0G3jDp5iK', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/followup.py', 'line': 55, 'name': '_contextualizer'}, 'invocation': {'file': 'rag/followup.py', 'line': 81, 'function': 'standalone_question'}, 'file': 'rag/followup.py', 'line': 81, 'function': 'standalone_question', 'agent_name': 'standalone_question', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            question = _gr_client.enforce(_gr_site, question, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        return question
    conversation = conversation_text(history)
    if summary:
        conversation = f"(Earlier: {' '.join(summary.split())[:400]}) / {conversation}"
    try:
        out = _contextualizer().invoke({"conversation": conversation, "question": question})
    except Exception:  # Ollama unavailable: fall back to the original question
        # LINEAJE: runtime guardrail checks `question` as it flows from the agent to the user interface, before it leaves the application (in standalone_question).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `question` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:00bbccf4267fb9f9abaf0024520f335aa02598d4108830d26743aa352790eee1'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:00bbccf4267fb9f9abaf0024520f335aa02598d4108830d26743aa352790eee1', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_m2lqBnC0G3jDp5iK', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/followup.py', 'line': 55, 'name': '_contextualizer'}, 'invocation': {'file': 'rag/followup.py', 'line': 88, 'function': 'standalone_question'}, 'file': 'rag/followup.py', 'line': 88, 'function': 'standalone_question', 'agent_name': 'standalone_question', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            question = _gr_client.enforce(_gr_site, question, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        return question
    out = out.strip().strip('"').strip()
    out = out.splitlines()[0].strip() if out else ""
    out = re.sub(r"^(?:rewritten|standalone question)\s*:\s*", "", out, flags=re.IGNORECASE).strip('" ')
    # Guard against the model answering instead of rewriting.
    if not out or len(out) > max(200, 4 * len(question)) or not out.endswith("?"):
        # LINEAJE: runtime guardrail checks `question` as it flows from the agent to the user interface, before it leaves the application (in standalone_question).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `question` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:2e4501388228e34b837b977f864a7d49a431cffb2b31cca6d37bdf5bf9bd0079'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2e4501388228e34b837b977f864a7d49a431cffb2b31cca6d37bdf5bf9bd0079', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_m2lqBnC0G3jDp5iK', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/followup.py', 'line': 55, 'name': '_contextualizer'}, 'invocation': {'file': 'rag/followup.py', 'line': 94, 'function': 'standalone_question'}, 'file': 'rag/followup.py', 'line': 94, 'function': 'standalone_question', 'agent_name': 'standalone_question', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            question = _gr_client.enforce(_gr_site, question, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        return question
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in standalone_question).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:fe9c80a70d766e9c4583cad0532dbd7a2503533c03616405a445bda6eb14fef3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:fe9c80a70d766e9c4583cad0532dbd7a2503533c03616405a445bda6eb14fef3', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_m2lqBnC0G3jDp5iK', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/followup.py', 'line': 55, 'name': '_contextualizer'}, 'invocation': {'file': 'rag/followup.py', 'line': 95, 'function': 'standalone_question'}, 'file': 'rag/followup.py', 'line': 95, 'function': 'standalone_question', 'agent_name': 'standalone_question', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out
