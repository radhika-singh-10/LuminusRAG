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

# Evaluation
EVAL_DATASET = Path(os.getenv("EVAL_DATASET", ROOT / "eval" / "dataset.jsonl"))
EVAL_RESULTS_DIR = Path(os.getenv("EVAL_RESULTS_DIR", ROOT / "eval" / "results"))
NLI_MODEL = os.getenv("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli")
