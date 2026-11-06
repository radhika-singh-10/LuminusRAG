# Retrieval-Augmented Generation (RAG)

RAG combines a retriever with a language model. At query time the system embeds
the question, fetches the most similar chunks from a vector store, and passes
them to the model as context so the answer is grounded in your documents.

## Pipeline stages

1. Load: read PDFs, text and markdown files.
2. Split: break documents into overlapping chunks (for example 1000 characters
   with 150 characters of overlap) so each piece fits an embedding model.
3. Embed: convert each chunk to a vector with a model such as
   all-MiniLM-L6-v2, which produces 384-dimensional embeddings.
4. Store: persist vectors in a database such as Chroma.
5. Retrieve: find the top-k nearest chunks to the question.
6. Generate: prompt the LLM with the chunks and the question.

## Common failure modes

- Chunks too large dilute relevance; chunks too small lose context.
- Missing overlap can split an answer across two chunks.
- Without an "answer only from context" instruction, models may hallucinate.
