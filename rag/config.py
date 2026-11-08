"""Central configuration, read from environment (.env supported)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
PERSIST_DIR = Path(os.getenv("PERSIST_DIR", ROOT / "chroma_db"))
COLLECTION = os.getenv("COLLECTION", "docs")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "huggingface")  # "huggingface" or "anthropic"
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-5")
HF_LLM_MODEL = os.getenv("HF_LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
HF_MAX_NEW_TOKENS = int(os.getenv("HF_MAX_NEW_TOKENS", "512"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
TOP_K = int(os.getenv("TOP_K", "8"))  # structure-aware chunks are ~400 chars; 8 ≈ the old 4 x 1000
SEARCH_TYPE = os.getenv("SEARCH_TYPE", "similarity")  # "similarity" or "mmr"

# GraphRAG: knowledge graph extracted from chunks by an Ollama model
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid")  # "vector", "graph", or "hybrid"
GRAPH_ENABLED = os.getenv("GRAPH_ENABLED", "true").lower() == "true"  # keep graph in sync on ingest
GRAPH_MODEL = os.getenv("GRAPH_MODEL", os.getenv("INTENT_MODEL", "llama3.2:3b"))
GRAPH_K = int(os.getenv("GRAPH_K", "2"))  # extra chunks contributed by the graph

# Versioned ingestion: new document versions go live atomically; old versions
# are garbage-collected in the background after a grace period.
GC_GRACE_SECONDS = float(os.getenv("GC_GRACE_SECONDS", "5"))
GC_STALE_BUILD_SECONDS = float(os.getenv("GC_STALE_BUILD_SECONDS", "3600"))

# Reranking: fetch more candidates, keep the TOP_K a cross-encoder scores best
RERANK = os.getenv("RERANK", "false").lower() == "true"
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_FETCH_K = int(os.getenv("RERANK_FETCH_K", "20"))

# History-aware retrieval: rewrite follow-ups into standalone questions
HISTORY_AWARE = os.getenv("HISTORY_AWARE", "true").lower() == "true"
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "3"))  # previous Q&A pairs used

# LLM-as-judge correctness (in addition to rule-based and NLI checks)
LLM_JUDGE = os.getenv("LLM_JUDGE", "false").lower() == "true"
JUDGE_MODEL = os.getenv("JUDGE_MODEL", os.getenv("INTENT_MODEL", "llama3.2:3b"))

# Intent gate (Ollama): only AI-related questions reach retrieval
INTENT_ENABLED = os.getenv("INTENT_ENABLED", "true").lower() == "true"
INTENT_MODEL = os.getenv("INTENT_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Policy guard: policies/*.json checked by regex + an Ollama model
GUARD_LLM = os.getenv("GUARD_LLM", "true").lower() == "true"
GUARD_MODEL = os.getenv("GUARD_MODEL", INTENT_MODEL)

# Web fallback: search online when the local store can't answer
WEB_FALLBACK = os.getenv("WEB_FALLBACK", "true").lower() == "true"
WEB_MIN_SCORE = float(os.getenv("WEB_MIN_SCORE", "0.25"))  # below this, skip local
WEB_MAX_RESULTS = int(os.getenv("WEB_MAX_RESULTS", "5"))
WEB_FETCH_PAGES = int(os.getenv("WEB_FETCH_PAGES", "3"))
WEB_TIMEOUT = float(os.getenv("WEB_TIMEOUT", "10"))
WEB_STORE = os.getenv("WEB_STORE", "true").lower() == "true"  # save web passages to Chroma
WEB_STORE_MIN_SCORE = float(os.getenv("WEB_STORE_MIN_SCORE", "0.45"))  # only save on-topic passages

# Chat history: LangChain SQLChatMessageHistory. Any SQLAlchemy URL works;
# default is a local SQLite file (gitignored).
CHAT_DB_URL = os.getenv("CHAT_DB_URL", f"sqlite:///{ROOT / 'chats' / 'history.sqlite'}")

# Evaluation
EVAL_DATASET = Path(os.getenv("EVAL_DATASET", ROOT / "eval" / "dataset.jsonl"))
EVAL_RESULTS_DIR = Path(os.getenv("EVAL_RESULTS_DIR", ROOT / "eval" / "results"))
NLI_MODEL = os.getenv("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli")

# Agent harness (rag/agent): multi-step conversations with follow-up
# suggestions and personalization from the conversation.
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "10"))         # questions per conversation
AGENT_MAX_FOLLOWUPS = int(os.getenv("AGENT_MAX_FOLLOWUPS", "3"))  # suggestions per answer
AGENT_MODEL = os.getenv("AGENT_MODEL", INTENT_MODEL)  # follow-ups + rolling summary (Ollama)
FOLLOWUP_MIN_SCORE = float(os.getenv("FOLLOWUP_MIN_SCORE", "0.5"))  # cosine to an active chunk
FOLLOWUP_MIN_RELEVANCE = float(os.getenv("FOLLOWUP_MIN_RELEVANCE", "0.25"))  # cosine to the question or answer
SUMMARY_EVERY = int(os.getenv("SUMMARY_EVERY", "3"))  # refresh the rolling summary every N steps
AGENT_ONLINE_NLI = os.getenv("AGENT_ONLINE_NLI", "false").lower() == "true"  # NLI per turn
# Personalization: interests = graph entities the user asked about, decayed per step
PERSONALIZE = os.getenv("PERSONALIZE", "true").lower() == "true"
INTEREST_DECAY = float(os.getenv("INTEREST_DECAY", "0.8"))
PERSONAL_WEIGHT = float(os.getenv("PERSONAL_WEIGHT", "0.15"))  # profile similarity in ranking
PPR_WEIGHT = float(os.getenv("PPR_WEIGHT", "0.1"))             # personalized PageRank in ranking
LONG_TERM_WEIGHT = float(os.getenv("LONG_TERM_WEIGHT", "0.3"))  # interests from the user's other chats
