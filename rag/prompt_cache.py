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
import threading
import time
from functools import lru_cache

from . import config

CACHE_HIT_MS_PER_TOKEN = 0.1  # cached prefixes evaluate ~0.01 ms/token, cold ~0.3


def chat_ollama(model: str | None = None, **kwargs):
    """ChatOllama with keep_alive set, so the model and its prompt cache stay loaded."""
    from langchain_ollama import ChatOllama

    return ChatOllama(model=model or config.INTENT_MODEL, base_url=config.OLLAMA_BASE_URL,
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
    return out


def warm(names: list[str] | None = None) -> dict:
    """Prefill system prompts (1 output token each). Returns {name: stats}."""
    results = {}
    for name, (model, prompt, sample) in system_prompts().items():
        if names and name not in names:
            continue
        t0 = time.perf_counter()
        try:
            r = _llm(model).invoke(prompt.invoke(sample))
            md = r.response_metadata or {}
            results[name] = {"prompt_tokens": md.get("prompt_eval_count"),
                             "prompt_ms": round((md.get("prompt_eval_duration") or 0) / 1e6),
                             "load_ms": round((md.get("load_duration") or 0) / 1e6),
                             "ms": round((time.perf_counter() - t0) * 1000)}
        except Exception as e:  # Ollama down: nothing to warm
            results[name] = {"error": f"{type(e).__name__}: {e}"}
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
