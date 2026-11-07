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
TOP_K = int(os.getenv("TOP_K", "4"))
SEARCH_TYPE = os.getenv("SEARCH_TYPE", "similarity")  # "similarity" or "mmr"

# GraphRAG: knowledge graph extracted from chunks by an Ollama model
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid")  # "vector", "graph", or "hybrid"
GRAPH_ENABLED = os.getenv("GRAPH_ENABLED", "true").lower() == "true"  # keep graph in sync on ingest
GRAPH_MODEL = os.getenv("GRAPH_MODEL", os.getenv("INTENT_MODEL", "llama3.2:3b"))
GRAPH_K = int(os.getenv("GRAPH_K", "2"))  # extra chunks contributed by the graph

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
