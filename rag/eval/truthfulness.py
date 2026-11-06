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
        ce = np.asarray(emb.embed_documents(claims))
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
