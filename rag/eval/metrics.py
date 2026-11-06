"""Pure metric functions (no models). Everything returns floats in [0, 1]."""
import math
import re
import string
from collections import Counter

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_CITATION = re.compile(r"\[\d+\]")
_REFUSAL_PATTERNS = re.compile(
    r"(i don'?t know|i do not know|not (?:contain|mention|provide|include)|"
    r"no information|cannot (?:answer|find|determine)|can'?t (?:answer|find|determine)|"
    r"does not (?:say|specify|state)|isn'?t (?:mentioned|specified)|not enough information)",
    re.IGNORECASE,
)


# ---------- text helpers ----------

def normalize(text: str) -> str:
    text = _CITATION.sub(" ", text.lower())
    text = "".join(ch if ch not in string.punctuation else " " for ch in text)
    text = _ARTICLES.sub(" ", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def is_refusal(answer: str) -> bool:
    return bool(_REFUSAL_PATTERNS.search(answer))


def contains_all(answer: str, phrases: list[str]) -> bool:
    norm = f" {normalize(answer)} "
    return all(f" {normalize(p)} " in norm for p in phrases)


def split_sentences(text: str) -> list[str]:
    """Answer -> claim-like sentences (citations stripped, tiny fragments dropped)."""
    text = _CITATION.sub("", text)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    out = []
    for p in parts:
        p = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", p).strip()
        if len(p.split()) >= 3:
            out.append(p)
    return out


# ---------- answer-level (token overlap, SQuAD-style) ----------

def token_prf(prediction: str, reference: str) -> tuple[float, float, float]:
    pred, ref = tokens(prediction), tokens(reference)
    if not pred or not ref:
        return (float(pred == ref),) * 3
    common = sum((Counter(pred) & Counter(ref)).values())
    if common == 0:
        return 0.0, 0.0, 0.0
    p, r = common / len(pred), common / len(ref)
    return p, r, 2 * p * r / (p + r)


def exact_match(prediction: str, reference: str) -> float:
    return float(normalize(prediction) == normalize(reference))


# ---------- retrieval ----------

def chunk_is_relevant(chunk_text: str, evidence: list[str]) -> bool:
    norm = normalize(chunk_text)
    return any(normalize(e) in norm for e in evidence)


def retrieval_metrics(chunks: list[str], evidence: list[str]) -> dict[str, float]:
    """Relevance is defined by evidence strings: a chunk is relevant if it
    contains any of them; recall is the fraction of evidence strings found."""
    rels = [chunk_is_relevant(c, evidence) for c in chunks]
    k = len(chunks)
    norm_chunks = [normalize(c) for c in chunks]
    found = sum(any(normalize(e) in c for c in norm_chunks) for e in evidence)

    first = next((i for i, r in enumerate(rels) if r), None)
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(rels) if r)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, max(1, sum(rels)))))
    return {
        "precision_at_k": sum(rels) / k if k else 0.0,
        "recall_at_k": found / len(evidence) if evidence else 0.0,
        "hit_rate": float(first is not None),
        "mrr": 1 / (first + 1) if first is not None else 0.0,
        "ndcg": dcg / ideal if ideal else 0.0,
    }


# ---------- sampling-based reliability ----------

def pass_at_k(n: int, c: int, k: int) -> float:
    """P(at least one of k samples is correct), unbiased estimator (Chen et al. 2021)."""
    if k > n:
        raise ValueError(f"k={k} > n={n}")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k: P(all k samples are correct), unbiased estimator (tau-bench)."""
    if k > n:
        raise ValueError(f"k={k} > n={n}")
    return math.comb(c, k) / math.comb(n, k)


# ---------- citations ----------

def citation_metrics(answer: str, n_context: int) -> dict[str, float]:
    cited = [int(m) for m in re.findall(r"\[(\d+)\]", answer)]
    return {
        "has_citation": float(bool(cited)),
        "citation_valid": float(all(1 <= c <= n_context for c in cited)) if cited else 0.0,
    }


def classification_prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}
