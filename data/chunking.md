# Chunking Strategies

Chunking decides what the retriever can find. A chunk is the unit that gets
embedded, retrieved and shown to the model, so a poor split can hide an answer
even when the document contains it.

## Fixed-size chunking

Fixed-size chunking cuts text every N characters or tokens. It is simple and
predictable, but it can break sentences and tables in the middle.

## Recursive chunking

Recursive chunking tries a list of separators in order: paragraph breaks first,
then line breaks, then spaces. It keeps paragraphs whole when they fit, and only
falls back to smaller separators when a piece is still too long. LangChain
provides this as RecursiveCharacterTextSplitter.

## Semantic chunking

Semantic chunking embeds consecutive sentences and starts a new chunk where the
similarity between neighbours drops sharply. It follows topic changes more
closely, but it costs more because every sentence must be embedded at ingestion.

## Structure-aware chunking

Structure-aware chunking splits on document structure such as markdown headings
or PDF sections, and can store the heading path as metadata. Tables and code
blocks should be kept intact where possible, because they lose their meaning
when they are cut apart.

## Choosing a size

Small chunks give precise matches but may lack context. Large chunks carry more
context but blur several topics into one vector. A common starting point is 500
to 1000 characters with 10 to 20 percent overlap, tuned against an evaluation
set rather than chosen by intuition.

The parent document pattern combines both: it searches over small chunks but
passes the larger section around each match to the model.
