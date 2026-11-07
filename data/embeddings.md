# Text Embeddings

An embedding is a list of numbers that represents the meaning of a piece of
text. Texts with similar meanings end up close together in the vector space,
even when they share no words, which is why embedding search can match
"car repair" with "fixing an automobile".

## Measuring similarity

Cosine similarity compares the angle between two vectors and ignores their
length. It ranges from -1 to 1, where 1 means the vectors point in the same
direction. When vectors are normalized to unit length, cosine similarity and
the dot product give the same result, and ranking by Euclidean distance gives
the same order.

## Choosing a model

Larger embedding models usually retrieve better but are slower and need more
storage, because each extra dimension adds to every stored vector. A float32
vector takes 4 bytes per dimension, so a 384-dimensional vector needs 1,536
bytes before any index overhead.

Models also have a maximum input length. Text beyond that limit is truncated
and silently ignored, so chunks should stay within the limit of the embedding
model. The all-MiniLM-L6-v2 model truncates input at 256 word pieces by default.

## Keeping embeddings consistent

Queries and documents must be embedded with the same model. Vectors from two
different models live in unrelated spaces, so comparing them gives meaningless
scores. If you change the embedding model you must re-embed the whole corpus.

Domain matters too. A general-purpose model can miss specialist vocabulary in
legal or medical text, and a domain-tuned model may retrieve better there.
