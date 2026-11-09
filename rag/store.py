"""Vector store access (Chroma, persisted on disk) and the shared embedding model."""
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

from langchain_chroma import Chroma
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_huggingface import HuggingFaceEmbeddings

from . import config


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    # LINEAJE: runtime guardrail checks the model this client is built with as it flows from the agent to the LLM, before it is sent to the model (in get_embeddings).
    #   Detected: this statement moves data from the agent to the LLM with no runtime policy check (detection confidence: medium).
    #   Decision: the Guardrail evaluates AI_AGENT_ACTIVITY_LOG, AI_APP_SEC_006, AI_APP_SEC_028, AI_APP_SEC_070 (+1 more); a model that is not approved is refused before the client is built (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:ca43f90b0191e2e90c9bc38fa1842a1b5a288e9e26afdee9e85d0a9dbb7c0a2b'
    _lineaje_model_evidence = {'model': config.EMBED_MODEL, 'client': 'HuggingFaceEmbeddings', 'provider': 'langchain_huggingface', 'model_source': 'call_kwarg', 'project': 'luminusrag'}
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ca43f90b0191e2e90c9bc38fa1842a1b5a288e9e26afdee9e85d0a9dbb7c0a2b', phase='pre_model', boundary={'source': 'agent_config', 'sink': 'model'}, fail_mode='BLOCK', source_type='agent', destination_type='llm', components={'destination': {'entity_type': 'llm', 'name': 'config.EMBED_MODEL', 'version': '', 'provider': ''}, 'invocation': {'file': 'rag/store.py', 'function': 'get_embeddings', 'line': 15}, 'file': 'rag/store.py', 'line': 15, 'function': 'get_embeddings', 'agent_name': 'get_embeddings', 'agent_name_source': 'inferred_from_function', 'boundary_id': 'bnd:0086b7c97d0a7471'})
    try:
        _lineaje_model_evidence = _gr_client.enforce(_gr_site, _lineaje_model_evidence, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        raise
    return HuggingFaceEmbeddings(
        model_name=config.EMBED_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vectorstore(persist_dir=None) -> Chroma:
    return Chroma(
        collection_name=config.COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=str(persist_dir or config.PERSIST_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


class ActiveVectorRetriever(BaseRetriever):
    """Vector search that only returns chunks of ACTIVE document versions
    (plus web passages). Chunks of a version still being built, of retired
    versions awaiting garbage collection, and legacy chunks are skipped, so a
    document switches to its new version atomically. Over-fetches and widens
    the search until k live chunks are found."""

    k: int = 4
    search_type: str = "similarity"

    def _get_relevant_documents(self, query: str, *,
                                run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        from .versioning import is_active

        store = get_vectorstore()
        n = self.k * 3
        for _ in range(4):
            if self.search_type == "mmr":
                docs = store.max_marginal_relevance_search(query, k=n, fetch_k=max(20, n * 4))
                # LINEAJE: runtime guardrail checks `docs` as it flows from a vector store to the agent, after the tool returns (in ActiveVectorRetriever._get_relevant_documents).
                #   Detected: this statement moves data from a vector store to the agent with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `docs` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:a1913e65d3d26a8b664ff2acb6804ba472d2ae02a8b86683bb43513df4363699'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:a1913e65d3d26a8b664ff2acb6804ba472d2ae02a8b86683bb43513df4363699', phase='post_tool', boundary={'source': 'vector_store', 'sink': 'agent_context'}, fail_mode='ALLOW_WITH_AUDIT', source_type='vector_store', destination_type='agent', components={'destination': {'entity_type': 'rag', 'unique_org_id': 'vdna_m2lqBnC0G3jDp5iK', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/store.py', 'line': 30, 'name': 'ActiveVectorRetriever'}, 'invocation': {'file': 'rag/store.py', 'line': 48, 'function': 'ActiveVectorRetriever._get_relevant_documents'}, 'file': 'rag/store.py', 'line': 48, 'function': '_get_relevant_documents', 'agent_name': 'ActiveVectorRetriever', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
                try:
                    docs = _gr_client.enforce(_gr_site, docs, content_type='application/json', variable_name='docs', source_file=__file__, before_line=48)
                except _gr_client.GuardrailUnavailableError:
                    pass
            else:
                docs = store.similarity_search(query, k=n)
                # LINEAJE: runtime guardrail checks `docs` as it flows from a vector store to the agent, after the tool returns (in ActiveVectorRetriever._get_relevant_documents).
                #   Detected: this statement moves data from a vector store to the agent with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `docs` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:f00105191fa97273aab6484a332fc21edb49bd5af154e239bf451ca6e41c847d'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:f00105191fa97273aab6484a332fc21edb49bd5af154e239bf451ca6e41c847d', phase='post_tool', boundary={'source': 'vector_store', 'sink': 'agent_context'}, fail_mode='ALLOW_WITH_AUDIT', source_type='vector_store', destination_type='agent', components={'destination': {'entity_type': 'rag', 'file_path': 'rag/store.py', 'line': 22, 'name': 'Chroma', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_m2lqBnC0G3jDp5iK'}, 'invocation': {'file': 'rag/store.py', 'function': 'ActiveVectorRetriever._get_relevant_documents', 'line': 50}, 'source': {'entity_type': 'rag', 'file_path': 'rag/store.py', 'line': 30, 'name': 'ActiveVectorRetriever', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'unique_org_id': 'vdna_m2lqBnC0G3jDp5iK'}, 'file': 'rag/store.py', 'line': 50, 'function': '_get_relevant_documents', 'agent_name': 'ActiveVectorRetriever', 'agent_name_source': 'inferred_from_class', 'boundary_id': 'bnd:a8b6773c6b85a73b'})
                try:
                    docs = _gr_client.enforce(_gr_site, docs, content_type='application/json', variable_name='docs', source_file=__file__, before_line=50)
                except _gr_client.GuardrailUnavailableError:
                    pass
            live = [d for d in docs if d.id and is_active(d.id)]
            if len(live) >= self.k or len(docs) < n:
                return live[: self.k]
            n *= 2
        return live[: self.k]


def get_retriever(k: int | None = None):
    """Vector retriever, wrapped with knowledge-graph context when
    RETRIEVAL_MODE is "graph" or "hybrid" (see rag/graph.py), and with a
    cross-encoder reranker when RERANK is on (see rag/rerank.py)."""
    k = k or config.TOP_K
    fetch = max(config.RERANK_FETCH_K, k) if config.RERANK else k
    retriever = ActiveVectorRetriever(k=fetch, search_type=config.SEARCH_TYPE)
    if config.RETRIEVAL_MODE in ("graph", "hybrid"):
        from .graph import HybridRetriever

        retriever = HybridRetriever(vector=retriever, mode=config.RETRIEVAL_MODE)
    if config.RERANK:
        from .rerank import RerankRetriever

        retriever = RerankRetriever(base=retriever, k=k)
    return retriever


def distance_to_cosine(store: Chroma, distance: float) -> float:
    """Chroma distance -> cosine similarity for unit-length embeddings. The
    metric depends on how the collection was created (older stores use l2)."""
    try:
        space = (store._collection.configuration_json.get("hnsw") or {}).get("space")
        # LINEAJE: runtime guardrail checks `space` as it flows from an external API to the agent, after the tool returns (in distance_to_cosine).
        #   Detected: this statement moves data from an external API to the agent with no runtime policy check (detection confidence: medium).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `space` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:54980a870a6cd90726d890de81ad543ba4cecebdf22166a3ce8135ff4c31facc'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:54980a870a6cd90726d890de81ad543ba4cecebdf22166a3ce8135ff4c31facc', phase='post_tool', boundary={'source': 'external_endpoint', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='api', destination_type='agent', components={'invocation': {'file': 'rag/store.py', 'line': 80, 'function': 'distance_to_cosine'}, 'file': 'rag/store.py', 'line': 80, 'function': 'distance_to_cosine', 'agent_name': 'distance_to_cosine', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            space = _gr_client.enforce(_gr_site, space, content_type='application/json', variable_name='space', source_file=__file__, before_line=80)
        except _gr_client.GuardrailUnavailableError:
            pass
    except Exception:
        space = None
    space = space or (store._collection.metadata or {}).get("hnsw:space", "l2")
    return 1 - distance / 2 if space == "l2" else 1 - distance
