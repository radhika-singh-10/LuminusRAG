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
        q = np.asarray(get_embeddings().embed_query(question))
        sims = {n: float(vecs[index[n]] @ q) for n in cands if n in index}
        related = sorted((n for n in sims if sims[n] >= SOURCE_MIN_SIM), key=lambda n: -sims[n])
        for n in related[:MAX_SOURCE_ENTITIES]:
            out[n] = (g.nodes[n]["name"], SOURCE_WEIGHT)
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
            return get_retriever(self.k).invoke(query, {"callbacks": run_manager.get_child()})

        emb = get_embeddings()
        store = get_vectorstore()
        q = np.asarray(emb.embed_query(query))
        p = profile_vector(self.interests)
        if p is None:
            return get_retriever(self.k).invoke(query, {"callbacks": run_manager.get_child()})

        # 1. ANN candidates: the question, and the question nudged toward the profile.
        fetch = self.k * 3
        nudged = q + config.PERSONAL_WEIGHT * p
        nudged = nudged / np.linalg.norm(nudged)
        pool: dict[str, Document] = {}
        for vec in (q, nudged):
            for d in store.similarity_search_by_vector(vec.tolist(), k=fetch):
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
        dv = np.asarray(emb.embed_documents([pool[i].page_content for i in ids]))
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
        return docs
