"""Truthfulness via a local NLI cross-encoder (no API key needed).

Each answer is split into claim sentences; each retrieved chunk is split into
premise windows of 1-3 consecutive sentences (NLI models break down on long,
multi-topic premises).

- faithfulness: share of claims entailed by at least one premise window
  (groundedness; 1 - faithfulness is the unsupported-claim rate)
- contradiction_rate: share of unsupported claims that are contradicted by one
  of the windows most similar to the claim (similarity = embedding cosine), so
  unrelated sentences don't count as contradictions
- reference_entailment: P(answer entails the gold reference answer)

Known limit: a claim that summarizes a long list ("the stages are A, B, ... F")
can't be entailed by any 3-sentence window and will score as unsupported.
"""
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

import re
from functools import lru_cache

import numpy as np

from .. import config
from ..store import get_embeddings
from .metrics import split_sentences

THRESHOLD = 0.5
WINDOW = 3
CONTRA_TOP_N = 3


def premise_windows(text: str, size: int = WINDOW) -> list[str]:
    text = re.sub(r"\s*\n\s*(?![-*•#]|\d+[.)])", " ", text)  # re-join wrapped lines
    sents = [
        re.sub(r"^[#\s\-*•]+|^\d+[.)]\s*", "", s).strip()
        for s in re.split(r"(?<=[.!?])\s+|\n+", text)
    ]
    sents = [s for s in sents if len(s.split()) >= 3]
    out = []
    for w in range(1, size + 1):
        out += [" ".join(sents[i : i + w]) for i in range(len(sents) - w + 1)]
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in premise_windows).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:bf1b433aa6b0899df4db74df03a1757ba76527d852e6a298774660bdcdca833f'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:bf1b433aa6b0899df4db74df03a1757ba76527d852e6a298774660bdcdca833f', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_r9uOApyICHEEUJVz', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/eval/truthfulness.py', 'line': 44, 'name': 'NLIScorer'}, 'invocation': {'file': 'rag/eval/truthfulness.py', 'line': 41, 'function': 'premise_windows'}, 'file': 'rag/eval/truthfulness.py', 'line': 41, 'function': 'premise_windows', 'agent_name': 'premise_windows', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


class NLIScorer:
    def __init__(self, model_name: str | None = None):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name or config.NLI_MODEL)
        id2label = self.model.model.config.id2label
        labels = {v.lower(): int(k) for k, v in id2label.items()}
        self.ent, self.con = labels["entailment"], labels["contradiction"]

    def probs(self, pairs: list[tuple[str, str]]) -> np.ndarray:
        """(premise, hypothesis) pairs -> softmax probabilities [n, 3]."""
        # LINEAJE: runtime guardrail checks `pairs` as it flows from the agent to the LLM, before it is sent to the model (in NLIScorer.probs).
        #   Detected: this statement moves data from the agent to the LLM with no runtime policy check (detection confidence: medium).
        #   Decision: the Guardrail evaluates AI_AGENT_ACTIVITY_LOG, AI_APP_SEC_006, AI_APP_SEC_028, AI_APP_SEC_070 (+2 more); sensitive values in `pairs` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:2ed0924971384a563c2aa6bdedc55d95e4ac05aafd0fc9fd54b0d74593135a7b'
        _lineaje_pairs_evidence = {'pairs': pairs, 'model': getattr(_lineaje_load_gr_client(), 'current_model', lambda _f: '')(__file__)}
        _gr_client = _lineaje_load_gr_client()
        _lineaje_interaction_id = _gr_client.new_interaction_id()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2ed0924971384a563c2aa6bdedc55d95e4ac05aafd0fc9fd54b0d74593135a7b', phase='pre_model', boundary={'source': 'agent_message', 'sink': 'model'}, fail_mode='BLOCK', source_type='agent', destination_type='llm', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_r9uOApyICHEEUJVz', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/eval/truthfulness.py', 'line': 44, 'name': 'NLIScorer'}, 'destination': {'entity_type': 'llm', 'name': 'llama3.2:3b', 'version': '', 'provider': 'meta'}, 'invocation': {'file': 'rag/eval/truthfulness.py', 'line': 55, 'function': 'NLIScorer.probs'}, 'file': 'rag/eval/truthfulness.py', 'line': 55, 'function': 'probs', 'agent_name': 'NLIScorer', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True}, interaction_id=_lineaje_interaction_id)
        try:
            _lineaje_pairs_evidence = _gr_client.enforce(_gr_site, _lineaje_pairs_evidence, content_type='application/json')
            pairs = _lineaje_pairs_evidence.get('pairs', pairs) if isinstance(_lineaje_pairs_evidence, dict) else pairs
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            raise
        return np.asarray(
            self.model.predict(pairs, apply_softmax=True, show_progress_bar=False)
        )

    def faithfulness(self, answer: str, contexts: list[str]) -> dict:
        claims = split_sentences(answer)
        premises = [w for c in contexts for w in premise_windows(c)]
        if not claims or not premises:
            # Too short to check as standalone claims (e.g. "384"); left out of
            # faithfulness. Correctness still covers these answers.
            return {"faithfulness": None, "contradiction_rate": None, "n_claims": len(claims)}

        p = self.probs([(w, c) for c in claims for w in premises])
        p = p.reshape(len(claims), len(premises), -1)
        supported = p[:, :, self.ent].max(axis=1) >= THRESHOLD

        emb = get_embeddings()
        # LINEAJE: runtime guardrail checks `claims` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in NLIScorer.faithfulness).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `claims` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:00af95c1fe78c9875e8e103a0ee6a60a2a195d99c13bc463a5618f933d291cff'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:00af95c1fe78c9875e8e103a0ee6a60a2a195d99c13bc463a5618f933d291cff', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_r9uOApyICHEEUJVz', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/eval/truthfulness.py', 'line': 44, 'name': 'NLIScorer'}, 'invocation': {'file': 'rag/eval/truthfulness.py', 'line': 72, 'function': 'NLIScorer.faithfulness'}, 'file': 'rag/eval/truthfulness.py', 'line': 72, 'function': 'faithfulness', 'agent_name': 'NLIScorer', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            claims = _gr_client.enforce(_gr_site, claims, content_type='application/json', variable_name='claims', source_file=__file__, before_line=72)
        except _gr_client.GuardrailUnavailableError:
            pass
        ce = np.asarray(emb.embed_documents(claims))
        # LINEAJE: runtime guardrail checks `premises` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in NLIScorer.faithfulness).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `premises` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:1e7251a2760036c28d7c3a52b3eecf81b3b12c47b8ece48a7b638edb30001afd'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1e7251a2760036c28d7c3a52b3eecf81b3b12c47b8ece48a7b638edb30001afd', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_r9uOApyICHEEUJVz', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'rag/eval/truthfulness.py', 'line': 44, 'name': 'NLIScorer'}, 'invocation': {'file': 'rag/eval/truthfulness.py', 'line': 73, 'function': 'NLIScorer.faithfulness'}, 'file': 'rag/eval/truthfulness.py', 'line': 73, 'function': 'faithfulness', 'agent_name': 'NLIScorer', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            premises = _gr_client.enforce(_gr_site, premises, content_type='application/json', variable_name='premises', source_file=__file__, before_line=73)
        except _gr_client.GuardrailUnavailableError:
            pass
        pe = np.asarray(emb.embed_documents(premises))
        nearest = np.argsort(-(ce @ pe.T), axis=1)[:, :CONTRA_TOP_N]
        contra_near = np.take_along_axis(p[:, :, self.con], nearest, axis=1).max(axis=1)
        contradicted = (~supported) & (contra_near >= THRESHOLD)

        return {
            "faithfulness": float(supported.mean()),
            "contradiction_rate": float(contradicted.mean()),
            "n_claims": len(claims),
            "unsupported_claims": [c for c, s in zip(claims, supported) if not s],
        }

    def entails(self, premise: str, hypothesis: str) -> float:
        return float(self.probs([(premise, hypothesis)])[0][self.ent])


@lru_cache(maxsize=1)
def get_scorer() -> NLIScorer:
    return NLIScorer()
