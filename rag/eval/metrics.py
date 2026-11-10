"""Pure metric functions (no models). Everything returns floats in [0, 1]."""
# Copyright (c) Lineaje, Inc. All rights reserved.
# Lineaje UnifAI guardrail  version=2.0.0-alpha
def _lineaje_gr_load(_f):
    """Lineaje-added: load gr_stub_client.py beside _f or in one of its 7 parent folders. Missing or broken:
    a pass-through client and ONE warning per process (GR_REQUIRE_CLIENT=1: ImportError instead)."""
    import sys, os, logging, importlib.util as u, pathlib
    n = "_lineaje_gr_stub_client"
    if n in sys.modules: return sys.modules[n]
    h = pathlib.Path(_f or ".").resolve().parent
    d = [h, *h.parents][:8]
    p = next((x / "gr_stub_client.py" for x in d if (x / "gr_stub_client.py").is_file()), None)
    try:
        s = u.spec_from_file_location(n, p) if p else None
        if s is None: raise FileNotFoundError("gr_stub_client.py")
        m = sys.modules[n] = u.module_from_spec(s); s.loader.exec_module(m); return m
    except Exception as e:
        sys.modules.pop(n, None)
        w = ("gr_stub_client.py not found for %s (searched: %s)" % (_f or "<no __file__>", ", ".join(map(str, d)))
             if p is None else "%s failed to load (%s%s)" % (p, type(e).__name__,
                                                          " line %s" % e.lineno if isinstance(e, SyntaxError) else ""))
        w = ("Lineaje guardrail NOT active: " + w + ". Calls pass through unchecked; set GR_REQUIRE_CLIENT=1 to fail "
             "instead. Each deploy unit needs gr_stub_client.py beside its code and GR_SERVICE_URL plus credentials as "
             "environment variables.")
        if os.environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": raise ImportError(w) from (None if p is None else e)
        z = sys.__dict__.setdefault("_lineaje_gr_null", __import__('types').SimpleNamespace(STUB_API=999999, GuardrailUnavailableError=type('GuardrailUnavailableError', (PermissionError,), {}), SiteDescriptor=lambda *a, **k: None, new_interaction_id=lambda *a, **k: None, enforce=lambda _s, _p, *a, **k: _p, enforce_request=lambda _s, _p, *a, **k: _p, enforce_reply=lambda _s, _p, *a, **k: _p, _lineaje_seen=set()))
        k = "missing" if p is None else (str(p), type(e).__name__)
        if k not in z._lineaje_seen:
            z._lineaje_seen.add(k); g = logging.getLogger("lineaje.guardrail"); g.log(30 if p is None else 40, w)
            if g.hasHandlers(): sys.stderr.write(w + "\n")
        return z
__import__("sys").__dict__.setdefault("_lineaje_gr_load_v1", _lineaje_gr_load)
del _lineaje_gr_load
def _lineaje_load_gr_client():
    """Lineaje-added: this file's gr_stub_client.py (the loader _lineaje_gr_load registered)."""
    return __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))
if __import__("os").environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))

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
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in split_sentences).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:c5b2b2770e6981f66a8959d629a2b6e49429bb5b71365f24e7b6bea71e54e5ed'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c5b2b2770e6981f66a8959d629a2b6e49429bb5b71365f24e7b6bea71e54e5ed', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/metrics.py', 'line': 48, 'function': 'split_sentences'}, 'file': 'rag/eval/metrics.py', 'line': 48, 'function': 'split_sentences', 'agent_name': 'split_sentences', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
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
