# Vector Databases

A vector database stores embeddings together with the original text and
metadata, and answers nearest-neighbour queries. Common options include Chroma,
FAISS, Qdrant, Weaviate, Milvus and pgvector. FAISS is a library rather than a
full database server, and pgvector adds vector search to PostgreSQL.

## Exact and approximate search

Exact search compares the query with every stored vector, so its cost grows
linearly with the size of the collection. Approximate nearest neighbour (ANN)
search trades a small loss of recall for much faster queries.

HNSW, short for Hierarchical Navigable Small World, is a popular ANN index. It
builds a layered graph: searches start in the sparse top layers and move down
to denser layers to refine the result. HNSW is fast but keeps its graph in
memory, so memory use is its main cost.

IVF indexes take a different approach. They cluster the vectors and search only
the clusters closest to the query.

## Metadata filtering

Most vector databases can filter on metadata during a search, for example
restricting results to one source file or a date range. Filtering is useful for
multi-tenant systems, where one customer must never see the documents of
another.

## Updating data

Stable document ids make updates safe. If a chunk id is derived from the content
of a file, re-running ingestion can skip files that did not change. Without
stable ids, re-ingesting a file adds duplicate chunks, and duplicates crowd out
other results in the top-k.
