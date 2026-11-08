"""Cross-encoder reranking.

The base retriever (vector, graph or hybrid) fetches RERANK_FETCH_K
candidates; a cross-encoder scores each (question, passage) pair jointly and
the best TOP_K are kept. Cross-encoders read the question and passage
together, so they judge relevance more precisely than embedding similarity,
at the cost of one model pass per candidate. Knowledge-graph fact summaries
are not reranked and are always kept.
"""
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
