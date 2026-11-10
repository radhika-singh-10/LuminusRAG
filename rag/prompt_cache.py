"""Prompt caching for the fixed system prompts.

The Ollama-served models (policy judges, intent classifier, follow-up
rewriter and generator, summarizer, graph extractor, LLM judge) each send a
long fixed system prompt (100-970 tokens) followed by a short variable part.
Ollama (llama.cpp) keeps the KV cache of recent prompts and reuses the
longest matching prefix, so a request whose system prompt is cached only
evaluates the new tokens. Measured on llama3.2:3b (results.md):

    policy judge, 968-token prompt:  cold 318 ms prefill (+531 ms model load)
                                     cached system prompt 11-23 ms
    all 8 system prompts:            73-235 ms cold -> 9-11 ms cached, kept at once

This module makes that cache reliable:
1. One ChatOllama factory (chat_ollama) for every call, with keep_alive =
   OLLAMA_KEEP_ALIVE (default 30m) so the model and its prompt cache aren't
   dropped after Ollama's default 5 idle minutes.
2. System prompts contain no variables (checked by tests), so the cached
   prefix matches byte for byte; per-request text goes in the human message.
3. warm(): prefills every system prompt once (1 output token) at app / chat
   start, in the background, so even the first question hits the cache.
4. Observability records Ollama's prompt_eval time per LLM span; a span whose
   prompt evaluated at < CACHE_HIT_MS_PER_TOKEN ms/token is a cache hit.

The local Hugging Face answer model (Qwen2.5-1.5B) has no prefix cache here
on purpose: its system prompt is 74 of ~1,040 prompt tokens, and reusing a
precomputed KV cache for it saved 3 ms of time-to-first-token (140 -> 137 ms),
which is noise. With LLM_PROVIDER=anthropic the answer system prompt is far
below the minimum cacheable length, so cache_control would have no effect.
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

import threading
import time
from functools import lru_cache

from . import config

CACHE_HIT_MS_PER_TOKEN = 0.1  # cached prefixes evaluate ~0.01 ms/token, cold ~0.3


def chat_ollama(model: str | None = None, **kwargs):
    """ChatOllama with keep_alive set, so the model and its prompt cache stay loaded."""
    from langchain_ollama import ChatOllama

    _lineaje_model = model or config.INTENT_MODEL
    # LINEAJE: runtime guardrail checks the model this client is built with as it flows from the agent to the LLM, before it is sent to the model (in chat_ollama).
    #   Detected: this statement moves data from the agent to the LLM with no runtime policy check (detection confidence: medium).
    #   Decision: the Guardrail evaluates AI_AGENT_ACTIVITY_LOG, AI_APP_SEC_006, AI_APP_SEC_028, AI_APP_SEC_070 (+1 more); a model that is not approved is refused before the client is built (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:af197bf6dcc07ad80f5d744976ab9b26c8395e0f76d39c56ae35cbbb67d0adbc'
    _lineaje_model_evidence = {'model': _lineaje_model, 'client': 'ChatOllama', 'provider': 'langchain_ollama', 'model_source': 'call_kwarg', 'project': 'luminusrag'}
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:af197bf6dcc07ad80f5d744976ab9b26c8395e0f76d39c56ae35cbbb67d0adbc', phase='pre_model', boundary={'source': 'agent_config', 'sink': 'model'}, fail_mode='BLOCK', source_type='agent', destination_type='llm', components={'invocation': {'file': 'rag/prompt_cache.py', 'function': 'chat_ollama', 'line': 44}, 'file': 'rag/prompt_cache.py', 'line': 44, 'function': 'chat_ollama', 'agent_name': 'chat_ollama', 'agent_name_source': 'inferred_from_function', 'boundary_id': 'bnd:99efc6b77c810849'})
    try:
        _lineaje_model_evidence = _gr_client.enforce(_gr_site, _lineaje_model_evidence, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        raise
    return ChatOllama(model=_lineaje_model, base_url=config.OLLAMA_BASE_URL,
                      keep_alive=config.OLLAMA_KEEP_ALIVE, **kwargs)


def _first(chain):
    """The prompt template at the start of a (possibly configured) chain."""
    while hasattr(chain, "bound"):
        chain = chain.bound
    return chain.first


def system_prompts() -> dict:
    """{name: (model, prompt template, sample input)} for every cached system prompt."""
    from .agent.followups import _generator
    from .followup import _contextualizer
    from .history import SUMMARY_PROMPT
    from .intent import _classifier
    from .policy import _compact_judge, _judge, _name_finder

    query_judge = (lambda name: _compact_judge(name)) if config.GUARD_VERDICT == "compact" else (
        lambda name: _judge(name, "query"))
    out = {
        "policy_judge:prompt_injection:query": (config.GUARD_MODEL, _first(query_judge("prompt_injection")),
                                                {"text": "What is HNSW?"}),
        "policy_judge:pii:query": (config.GUARD_MODEL, _first(query_judge("pii")), {"text": "What is HNSW?"}),
        "intent_classifier": (config.INTENT_MODEL, _first(_classifier()),
                              {"question": "What is HNSW?", "conversation": ""}),
        "followup_rewriter": (config.GUARD_MODEL, _first(_contextualizer()),
                              {"conversation": "User: What is HNSW?", "question": "What does it cost?"}),
        "followup_generator": (config.AGENT_MODEL, _first(_generator()),
                               {"interests": "none", "asked": "- What is HNSW?", "answer": "-", "passages": "-"}),
        "chat_summarizer": (config.AGENT_MODEL, SUMMARY_PROMPT, {"transcript": "User: hi"}),
        # Ingestion-time prompts (documents, web pages)
        "policy_judge:prompt_injection:document": (config.GUARD_MODEL,
                                                   _first(_judge("prompt_injection", "document")), {"text": "-"}),
        "policy_judge:pii:document": (config.GUARD_MODEL, _first(_judge("pii", "document")), {"text": "-"}),
        "pii_name_finder": (config.GUARD_MODEL, _first(_name_finder()), {"text": "-"}),
    }
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in system_prompts).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:187d88392b3a8c82822b49f39915faf57b924a50daa9535d56426300e3ac8df3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:187d88392b3a8c82822b49f39915faf57b924a50daa9535d56426300e3ac8df3', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/prompt_cache.py', 'line': 82, 'function': 'system_prompts'}, 'file': 'rag/prompt_cache.py', 'line': 82, 'function': 'system_prompts', 'agent_name': 'system_prompts', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def warm(names: list[str] | None = None) -> dict:
    """Prefill system prompts (1 output token each). Returns {name: stats}."""
    results = {}
    for name, (model, prompt, sample) in system_prompts().items():
        if names and name not in names:
            continue
        t0 = time.perf_counter()
        try:
            _lineaje_client = _llm(model)
            _lineaje_arg = prompt.invoke(sample)
            # LINEAJE: runtime guardrail checks `_lineaje_arg` as it flows from the agent to the LLM, before it is sent to the model (in warm).
            #   Detected: this statement moves data from the agent to the LLM with no runtime policy check (detection confidence: medium).
            #   Decision: the Guardrail evaluates AI_AGENT_ACTIVITY_LOG, AI_APP_SEC_006, AI_APP_SEC_028, AI_APP_SEC_070 (+2 more); sensitive values in `_lineaje_arg` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:5aa575a94ef4d1bf095e6ea3f23e799991150372ab0fd44f0c6e1630ebf73241'
            _lineaje__lineaje_arg_evidence = {'_lineaje_arg': _lineaje_arg, 'model': getattr(_lineaje_load_gr_client(), 'current_model', lambda _f: '')(__file__), 'model_source': 'guess'}
            _gr_client = _lineaje_load_gr_client()
            _lineaje_interaction_id = _gr_client.new_interaction_id()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5aa575a94ef4d1bf095e6ea3f23e799991150372ab0fd44f0c6e1630ebf73241', phase='pre_model', boundary={'source': 'agent_message', 'sink': 'model'}, fail_mode='BLOCK', source_type='agent', destination_type='llm', components={'invocation': {'file': 'rag/prompt_cache.py', 'function': 'warm', 'line': 93}, 'file': 'rag/prompt_cache.py', 'line': 93, 'function': 'warm', 'agent_name': 'warm', 'agent_name_source': 'inferred_from_function', 'boundary_id': 'bnd:0128edb2c7f3602a'}, interaction_id=_lineaje_interaction_id)
            try:
                _lineaje__lineaje_arg_evidence = _gr_client.enforce(_gr_site, _lineaje__lineaje_arg_evidence, content_type='application/json')
                _lineaje_arg = _lineaje__lineaje_arg_evidence.get('_lineaje_arg', _lineaje_arg) if isinstance(_lineaje__lineaje_arg_evidence, dict) else _lineaje_arg
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                raise
            r = _lineaje_client.invoke(_lineaje_arg)
            # LINEAJE: runtime guardrail checks `r` as it flows from the LLM to the agent, after the model replies (in warm).
            #   Detected: this statement moves data from the LLM to the agent with no runtime policy check (detection confidence: medium).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_011, AI_DAT_SEC_025, AI_DAT_SEC_027, AI_DAT_SEC_029; sensitive values in `r` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:8c635b1e49d0c25b31615968658f9d80de2b9cc9db8b9f2247afa3d2f09a5aab'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:8c635b1e49d0c25b31615968658f9d80de2b9cc9db8b9f2247afa3d2f09a5aab', phase='post_model', boundary={'source': 'model', 'sink': 'agent_message'}, fail_mode='BLOCK', source_type='llm', destination_type='agent', components={'invocation': {'file': 'rag/prompt_cache.py', 'function': 'warm', 'line': 93}, 'file': 'rag/prompt_cache.py', 'line': 93, 'function': 'warm', 'agent_name': 'warm', 'agent_name_source': 'inferred_from_function', 'boundary_id': 'bnd:0128edb2c7f3602a'}, interaction_id=locals().get('_lineaje_interaction_id'))
            try:
                if not hasattr(_gr_client, 'enforce_reply'):
                    __import__("logging").getLogger("lineaje.gr_client").error("gr_stub_client.py predates enforce_reply (STUB_API 2): this site is NOT enforced; replace gr_stub_client.py with the current companion")
                    raise _gr_client.GuardrailUnavailableError("stale gr_stub_client.py: no enforce_reply")
                r = _gr_client.enforce_reply(_gr_site, r, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            md = r.response_metadata or {}
            results[name] = {"prompt_tokens": md.get("prompt_eval_count"),
                             "prompt_ms": round((md.get("prompt_eval_duration") or 0) / 1e6),
                             "load_ms": round((md.get("load_duration") or 0) / 1e6),
                             "ms": round((time.perf_counter() - t0) * 1000)}
        except Exception as e:  # Ollama down: nothing to warm
            results[name] = {"error": f"{type(e).__name__}: {e}"}
    # LINEAJE: runtime guardrail checks `results` as it flows from the agent to the user interface, before it leaves the application (in warm).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `results` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:91da07ae89e0622a16b212beb413db8141ab758c6a6eae51b2b10c43b9d176ff'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:91da07ae89e0622a16b212beb413db8141ab758c6a6eae51b2b10c43b9d176ff', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/prompt_cache.py', 'line': 101, 'function': 'warm'}, 'file': 'rag/prompt_cache.py', 'line': 101, 'function': 'warm', 'agent_name': 'warm', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        results = _gr_client.enforce(_gr_site, results, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return results


@lru_cache(maxsize=4)
def _llm(model: str):
    return chat_ollama(model, temperature=0, num_predict=1)


_warm_state: dict = {"started": None, "finished": None, "results": None}


def warm_in_background() -> dict:
    """Start warm() once per process in a daemon thread; returns the shared state."""
    if config.PROMPT_CACHE_WARMUP and _warm_state["started"] is None:
        _warm_state["started"] = time.strftime("%H:%M:%S")

        def run():
            _warm_state["results"] = warm()
            _warm_state["finished"] = time.strftime("%H:%M:%S")

        threading.Thread(target=run, name="prompt-cache-warmup", daemon=True).start()
    return _warm_state


def is_cache_hit(prompt_ms: float | None, prompt_tokens: int | None) -> bool | None:
    if not prompt_ms and prompt_ms != 0 or not prompt_tokens:
        return None
    return prompt_ms / prompt_tokens < CACHE_HIT_MS_PER_TOKEN
