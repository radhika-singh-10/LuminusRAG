"""Vector store access (Chroma, persisted on disk) and the shared embedding model."""
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_huggingface import HuggingFaceEmbeddings

from . import config


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
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
            else:
                docs = store.similarity_search(query, k=n)
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
    except Exception:
        space = None
    space = space or (store._collection.metadata or {}).get("hnsw:space", "l2")
    return 1 - distance / 2 if space == "l2" else 1 - distance
