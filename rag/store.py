"""Vector store access (Chroma, persisted on disk) and the shared embedding model."""
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from . import config


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=config.EMBED_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vectorstore() -> Chroma:
    return Chroma(
        collection_name=config.COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=str(config.PERSIST_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def get_retriever(k: int | None = None):
    """Vector retriever, wrapped with knowledge-graph context when
    RETRIEVAL_MODE is "graph" or "hybrid" (see rag/graph.py), and with a
    cross-encoder reranker when RERANK is on (see rag/rerank.py)."""
    k = k or config.TOP_K
    fetch = max(config.RERANK_FETCH_K, k) if config.RERANK else k
    search_kwargs = {"k": fetch}
    if config.SEARCH_TYPE == "mmr":
        search_kwargs["fetch_k"] = max(20, fetch * 4)
    retriever = get_vectorstore().as_retriever(
        search_type=config.SEARCH_TYPE, search_kwargs=search_kwargs
    )
    if config.RETRIEVAL_MODE in ("graph", "hybrid"):
        from .graph import HybridRetriever

        retriever = HybridRetriever(vector=retriever, mode=config.RETRIEVAL_MODE)
    if config.RERANK:
        from .rerank import RerankRetriever

        retriever = RerankRetriever(base=retriever, k=k)
    return retriever
