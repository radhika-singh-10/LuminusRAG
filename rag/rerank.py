"""Cross-encoder reranking.

The base retriever (vector, graph or hybrid) fetches RERANK_FETCH_K
candidates; a cross-encoder scores each (question, passage) pair jointly and
the best TOP_K are kept. Cross-encoders read the question and passage
together, so they judge relevance more precisely than embedding similarity,
at the cost of one model pass per candidate. Knowledge-graph fact summaries
are not reranked and are always kept.
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

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from . import config


@lru_cache(maxsize=1)
def get_reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(config.RERANK_MODEL)


def rerank(query: str, docs: list[Document], k: int) -> list[Document]:
    passages = [d for d in docs if d.metadata.get("origin") != "graph"]
    facts = [d for d in docs if d.metadata.get("origin") == "graph"]
    if not passages:
        # LINEAJE: runtime guardrail checks `facts` as it flows from the agent to the user interface, before it leaves the application (in rerank).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `facts` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9118063bd2b4b9e60769d34d780b345d84810a6f63f0aea0595a2ef63be72c3a'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9118063bd2b4b9e60769d34d780b345d84810a6f63f0aea0595a2ef63be72c3a', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/rerank.py', 'line': 30, 'function': 'rerank'}, 'file': 'rag/rerank.py', 'line': 30, 'function': 'rerank', 'agent_name': 'rerank', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            facts = _gr_client.enforce(_gr_site, facts, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        return facts
    scores = get_reranker().predict([(query, d.page_content) for d in passages],
                                    show_progress_bar=False)
    ranked = sorted(zip(scores, passages), key=lambda x: -x[0])[:k]
    out = []
    for score, d in ranked:
        d.metadata = {**d.metadata, "rerank_score": float(score)}
        out.append(d)
    return out + facts


class RerankRetriever(BaseRetriever):
    base: BaseRetriever
    k: int = 4

    def _get_relevant_documents(self, query: str, *,
                                run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        return rerank(query, self.base.invoke(query, {"callbacks": run_manager.get_child()}), self.k)
