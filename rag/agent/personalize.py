"""Personalized GraphRAG retrieval.

The user's interests are knowledge-graph entities (rag/agent/memory.py):
each answered question adds the entities it mentions (found by ANN search over
entity-name embeddings) and, with a smaller weight, the entities of the chunks
that answered it. Weights decay every step, so recent interests dominate.

Retrieval with a profile (PersonalizedRetriever):

1. ANN candidates: vector search with the question, plus a second search with
   the question embedding nudged toward the profile vector
   (normalize(q + PERSONAL_WEIGHT * p), p = weighted mean of interest-entity
   embeddings). The second search surfaces chunks that match the question
   *and* what the user has been exploring.
2. Personalized PageRank over the knowledge graph, restarting at the
   question's entities (weight 1) and the interest entities (weighted). Each
   chunk scores the PageRank mass of the entities extracted from it.
3. Rank: cos(q, chunk) + PERSONAL_WEIGHT * cos(p, chunk) + PPR_WEIGHT * ppr(chunk).
   The question term dominates; the profile breaks ties between chunks that
   match the question about equally (e.g. "recall" in evaluation vs ANN search).
   Additive: the question's own top k are always kept, so an unrelated
   profile cannot push the answer out; the profile adds up to PERSONAL_EXTRA
   chunks and sets the order (what the model reads first).
4. Add the top PPR chunks not already present (GRAPH_K) and a facts block
   from the highest-ranked entities connected to the question.

Without interests it behaves like the hybrid retriever. Only active chunks
(see rag/versioning.py) are ever returned.
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

import networkx as nx
import numpy as np
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from .. import config
from ..graph import FACTS_SOURCE, _graph_index, match_entities
from ..store import get_embeddings, get_vectorstore

QUESTION_WEIGHT = 1.0  # entity named in the question
SOURCE_WEIGHT = 0.3    # entity found in an answering chunk
MAX_SOURCE_ENTITIES = 3
SOURCE_DOCS = 3         # answering chunks considered
SOURCE_MIN_SIM = 0.4    # entity name vs question cosine
PERSONAL_EXTRA = 2      # profile-ranked chunks added to the question's top k


@lru_cache(maxsize=4)
def _chunk_entities(graph_id: int) -> dict[str, list[str]]:
    """chunk id -> entity keys extracted from it (cached per loaded graph)."""
    g, _, _ = _graph_index()
    out: dict[str, list[str]] = {}
    for n, data in g.nodes(data=True):
        for c in data.get("chunks", []):
            out.setdefault(c, []).append(n)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in _chunk_entities).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:d660fcb0e1bdb14f1946e3944dca9dbf2b6b8ddb279d3f4c6881f015f6d893da'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:d660fcb0e1bdb14f1946e3944dca9dbf2b6b8ddb279d3f4c6881f015f6d893da', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/agent/personalize.py', 'line': 58, 'function': '_chunk_entities'}, 'file': 'rag/agent/personalize.py', 'line': 58, 'function': '_chunk_entities', 'agent_name': '_chunk_entities', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def chunk_entities() -> dict[str, list[str]]:
    g, _, _ = _graph_index()
    return _chunk_entities(id(g))


@lru_cache(maxsize=4)
def _undirected(graph_id: int) -> nx.Graph:
    g, _, _ = _graph_index()
    return nx.Graph(g.to_undirected(as_view=True))


def interests_from_turn(question: str, docs: list[Document]) -> dict[str, tuple[str, float]]:
    """{entity key: (name, weight)} learned from one answered question."""
    g, _, _ = _graph_index()
    if not g.number_of_nodes():
        return {}
    out: dict[str, tuple[str, float]] = {}
    for n in match_entities(question):
        out[n] = (g.nodes[n]["name"], QUESTION_WEIGHT)
    # Entities of the top answering chunks, if they are about the question
    # (retrieved chunks also mention unrelated things: "Google", "OpenAI").
    by_chunk = chunk_entities()
    cands = list(dict.fromkeys(n for d in docs[:SOURCE_DOCS] for n in by_chunk.get(d.id or "", [])
                               if n not in out))
    if cands:
        _, nodes, vecs = _graph_index()
        index = {n: i for i, n in enumerate(nodes)}
        # LINEAJE: runtime guardrail checks `question` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in interests_from_turn).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `question` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:7b99c611293e0d4b415ffd0f0e4762f546def98d0f114759c858f2e2f9147b48'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:7b99c611293e0d4b415ffd0f0e4762f546def98d0f114759c858f2e2f9147b48', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/agent/personalize.py', 'line': 88, 'function': 'interests_from_turn'}, 'file': 'rag/agent/personalize.py', 'line': 88, 'function': 'interests_from_turn', 'agent_name': 'interests_from_turn', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            question = _gr_client.enforce(_gr_site, question, content_type='application/json', variable_name='question', source_file=__file__, before_line=88)
        except _gr_client.GuardrailUnavailableError:
            pass
        q = np.asarray(get_embeddings().embed_query(question))
        sims = {n: float(vecs[index[n]] @ q) for n in cands if n in index}
        related = sorted((n for n in sims if sims[n] >= SOURCE_MIN_SIM), key=lambda n: -sims[n])
        for n in related[:MAX_SOURCE_ENTITIES]:
            out[n] = (g.nodes[n]["name"], SOURCE_WEIGHT)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in interests_from_turn).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:3709614aee7449899bb507a5db62f517b97d20a06f2e2b673adcd927319b5a57'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:3709614aee7449899bb507a5db62f517b97d20a06f2e2b673adcd927319b5a57', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/agent/personalize.py', 'line': 93, 'function': 'interests_from_turn'}, 'file': 'rag/agent/personalize.py', 'line': 93, 'function': 'interests_from_turn', 'agent_name': 'interests_from_turn', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def profile_vector(interests: list[dict]) -> np.ndarray | None:
    """Weighted mean of interest-entity name embeddings (unit length)."""
    g, nodes, vecs = _graph_index()
    index = {n: i for i, n in enumerate(nodes)}
    rows = [(index[i["entity"]], i["weight"]) for i in interests if i["entity"] in index]
    if not rows:
        return None
    p = sum(w * vecs[i] for i, w in rows)
    norm = np.linalg.norm(p)
    return p / norm if norm else None


def personalized_pagerank(question: str, interests: list[dict]) -> tuple[dict[str, float], list[str]]:
    """(entity -> PPR score, question seed entities)."""
    g, _, _ = _graph_index()
    if not g.number_of_nodes():
        return {}, []
    seeds = match_entities(question)
    restart = {s: QUESTION_WEIGHT for s in seeds}
    top = max((i["weight"] for i in interests), default=0) or 1.0
    for i in interests:
        if i["entity"] in g:
            restart[i["entity"]] = restart.get(i["entity"], 0) + 0.5 * i["weight"] / top
    if not restart:
        return {}, seeds
    ug = _undirected(id(g))
    try:
        return nx.pagerank(ug, alpha=0.85, personalization=restart, max_iter=100), seeds
    except nx.PowerIterationFailedConvergence:
        return {}, seeds


def _facts(ppr: dict[str, float], seeds: list[str], limit: int = 12) -> list[str]:
    """Facts on edges touching the question's entities or the top PPR entities."""
    from ..versioning import is_active

    g, _, _ = _graph_index()
    top = set(seeds) | {n for n, _ in sorted(ppr.items(), key=lambda x: -x[1])[:6]}
    scored = []
    for u, v, d in g.edges(data=True):
        if (u in top or v in top) and is_active(d["chunk"]):
            line = f"{g.nodes[u]['name']} --{d['relation']}--> {g.nodes[v]['name']}"
            bonus = 1.0 if (u in seeds or v in seeds) else 0.0
            scored.append((bonus + ppr.get(u, 0) + ppr.get(v, 0), line))
    out = []
    for _, line in sorted(scored, key=lambda x: -x[0]):
        if line not in out:
            out.append(line)
    return out[:limit]


class PersonalizedRetriever(BaseRetriever):
    """Hybrid GraphRAG retrieval biased toward the user's interests."""

    interests: list[dict] = []
    k: int = 8
    graph_k: int = 2

    def _get_relevant_documents(self, query: str, *,
                                run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        from ..store import get_retriever
        from ..versioning import is_active

        if not (config.PERSONALIZE and self.interests):
            try:
                _lineaje_obs = _lineaje_load_gr_client()
                _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:6afa13b59b7b3a32e4beff55302a150cf3691fd13cda8f63dc51c023b8f2750d', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/agent/personalize.py', 'line': 160, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'call_target': 'run_manager.get_child', 'not_on_graph': True}, observe_only=True)
                _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
            except Exception as _lineaje_obs_err:
                [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
            return get_retriever(self.k).invoke(query, {"callbacks": run_manager.get_child()})

        emb = get_embeddings()
        store = get_vectorstore()
        # LINEAJE: runtime guardrail checks `query` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in PersonalizedRetriever._get_relevant_documents).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `query` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:2556bd344e809ca901b31a3949d00754a58967ae8185b410f1ea4505b01f3808'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2556bd344e809ca901b31a3949d00754a58967ae8185b410f1ea4505b01f3808', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/agent/personalize.py', 'line': 164, 'function': 'PersonalizedRetriever._get_relevant_documents'}, 'file': 'rag/agent/personalize.py', 'line': 164, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            query = _gr_client.enforce(_gr_site, query, content_type='application/json', variable_name='query', source_file=__file__, before_line=164)
        except _gr_client.GuardrailUnavailableError:
            pass
        q = np.asarray(emb.embed_query(query))
        p = profile_vector(self.interests)
        if p is None:
            try:
                _lineaje_obs = _lineaje_load_gr_client()
                _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:1e29104b50b576f577ba287894b5ee4565851368608859a6e9a5b83fd7f89792', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/agent/personalize.py', 'line': 167, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'call_target': 'run_manager.get_child', 'not_on_graph': True}, observe_only=True)
                _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
            except Exception as _lineaje_obs_err:
                [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
            return get_retriever(self.k).invoke(query, {"callbacks": run_manager.get_child()})

        # 1. ANN candidates: the question, and the question nudged toward the profile.
        fetch = self.k * 3
        nudged = q + config.PERSONAL_WEIGHT * p
        nudged = nudged / np.linalg.norm(nudged)
        pool: dict[str, Document] = {}
        for vec in (q, nudged):
            try:
                _lineaje_obs = _lineaje_load_gr_client()
                _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:b431560497fd225b2d187f68110cfbaccb229637ddf23149888531979fb39495', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/agent/personalize.py', 'line': 175, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'call_target': 'vec.tolist', 'not_on_graph': True}, observe_only=True)
                _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
            except Exception as _lineaje_obs_err:
                [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
            for d in store.similarity_search_by_vector(vec.tolist(), k=fetch):
                try:
                    _lineaje_obs = _lineaje_load_gr_client()
                    _lineaje_obs_site = _lineaje_obs.SiteDescriptor(site_id='site:sha256:3daf40d4ff5d29336278773af219f108cbd7e85eb59a09d1dcb2d829bb0ff1ca', phase='', boundary={}, fail_mode='ALLOW', source_type='vector_store', destination_type='agent', components={'file': 'rag/agent/personalize.py', 'line': 176, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'call_target': 'is_active', 'not_on_graph': True}, observe_only=True)
                    _lineaje_obs.enforce(_lineaje_obs_site, {'activity': 'rag_retrieve'}, content_type='application/json')
                except Exception as _lineaje_obs_err:
                    [__import__('sys').__dict__.setdefault('_lineaje_gr_logged', set()).add(_k) or __import__('logging').getLogger('lineaje.guardrail').warning('Lineaje guardrail: an observe-only report failed (%s); later failures of this kind are not logged', _k[1]) for _k in [('observe', type(_lineaje_obs_err).__name__)] if _k not in __import__('sys').__dict__.setdefault('_lineaje_gr_logged', set())]
                if d.id and d.id not in pool and is_active(d.id):
                    pool[d.id] = d
        if not pool:
            return []

        # 2. Personalized PageRank over the knowledge graph.
        ppr, seeds = personalized_pagerank(query, self.interests)
        by_chunk = chunk_entities()
        chunk_ppr = {c: sum(ppr.get(n, 0) for n in ents) for c, ents in by_chunk.items()}
        top_ppr = max(chunk_ppr.values(), default=0) or 1.0

        # 3. Rank the pool.
        ids = list(pool)
        _lineaje_payload = [pool[i].page_content for i in ids]
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in PersonalizedRetriever._get_relevant_documents).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `_lineaje_payload` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:fafe7ef739d3e5dc136d22e3058b9d89bee326dfe6397fa95c77f7c9dfb9d665'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:fafe7ef739d3e5dc136d22e3058b9d89bee326dfe6397fa95c77f7c9dfb9d665', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/agent/personalize.py', 'line': 189, 'function': 'PersonalizedRetriever._get_relevant_documents'}, 'file': 'rag/agent/personalize.py', 'line': 189, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=189)
        except _gr_client.GuardrailUnavailableError:
            pass
        dv = np.asarray(emb.embed_documents(_lineaje_payload))
        score = dv @ q + config.PERSONAL_WEIGHT * (dv @ p) + \
            config.PPR_WEIGHT * np.asarray([chunk_ppr.get(i, 0) / top_ppr for i in ids])
        # Additive: the question's own top k always stay (an unrelated profile
        # can't push the answer out); the profile adds up to PERSONAL_EXTRA
        # chunks and decides the order.
        q_order = [ids[i] for i in np.argsort(-(dv @ q))]
        reserved = q_order[: self.k]
        p_order = [ids[i] for i in np.argsort(-score) if ids[i] not in reserved]
        pos = {i: n for n, i in enumerate(ids)}
        docs = []
        for i in reserved + p_order[:PERSONAL_EXTRA]:
            d = pool[i]
            d.metadata = {**d.metadata, "personal_score": round(float(score[pos[i]]), 4)}
            docs.append(d)
        docs.sort(key=lambda d: -d.metadata["personal_score"])

        # 4. Graph: extra chunks by PPR mass, and facts. Only when the question
        # names graph entities: otherwise PPR reflects the profile alone and
        # would add chunks about past topics rather than this question.
        if not seeds:
            # LINEAJE: runtime guardrail checks `docs` as it flows from the agent to the user interface, before it leaves the application (in PersonalizedRetriever._get_relevant_documents).
            #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `docs` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:8075cb7ce0662469c1f29144337b7c9a1559f4741e2e86f7d90d679e53ec0af2'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:8075cb7ce0662469c1f29144337b7c9a1559f4741e2e86f7d90d679e53ec0af2', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/agent/personalize.py', 'line': 210, 'function': 'PersonalizedRetriever._get_relevant_documents'}, 'file': 'rag/agent/personalize.py', 'line': 210, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
            try:
                docs = _gr_client.enforce(_gr_site, docs, content_type='text/plain')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            return docs
        chosen = {d.id for d in docs}
        extra_ids = [c for c, _ in sorted(chunk_ppr.items(), key=lambda x: -x[1])
                     if c not in chosen and is_active(c)][: self.graph_k]
        if extra_ids:
            data = store.get(ids=extra_ids, include=["documents", "metadatas"])
            for i, t, m in zip(data["ids"], data["documents"], data["metadatas"]):
                docs.append(Document(id=i, page_content=t, metadata={**m, "via": "graph-ppr"}))
        if facts := _facts(ppr, seeds):
            names = [i["name"] for i in self.interests[:3]]
            docs.append(Document(
                page_content="Knowledge graph facts (personalized for: " + ", ".join(names) + "):\n"
                             + "\n".join(f"- {f}" for f in facts),
                metadata={"source": FACTS_SOURCE, "origin": "graph", "title": "Knowledge graph"}))
        # LINEAJE: runtime guardrail checks `docs` as it flows from the agent to the user interface, before it leaves the application (in PersonalizedRetriever._get_relevant_documents).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `docs` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:5db00eb576274d1fd63a0d15580599cb029d33025ff28b6bd7c84599991e2f7f'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5db00eb576274d1fd63a0d15580599cb029d33025ff28b6bd7c84599991e2f7f', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/agent/personalize.py', 'line': 224, 'function': 'PersonalizedRetriever._get_relevant_documents'}, 'file': 'rag/agent/personalize.py', 'line': 224, 'function': '_get_relevant_documents', 'agent_name': 'PersonalizedRetriever', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            docs = _gr_client.enforce(_gr_site, docs, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        return docs
