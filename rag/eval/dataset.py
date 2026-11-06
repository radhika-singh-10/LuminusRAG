"""Eval dataset: one JSON object per line.

Fields:
  id              unique string
  question        the user question
  answerable      false if the corpus does not contain the answer (default true)
  reference       gold answer text (used for token P/R/F1 and NLI correctness)
  must_include    phrases that must all appear for the answer to count as correct
  evidence        substrings that identify relevant chunks (retrieval P/R)
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalItem:
    id: str
    question: str
    answerable: bool = True
    reference: str = ""
    must_include: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def load_dataset(path: Path) -> list[EvalItem]:
    items = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                items.append(EvalItem(**json.loads(line)))
            except (json.JSONDecodeError, TypeError) as e:
                raise ValueError(f"{path}:{lineno}: {e}") from e
    if not items:
        raise ValueError(f"No items in {path}")
    return items
