"""Measure the intent gate on labeled queries (eval/intent_dataset.jsonl).

Each line: {"question": "...", "allowed": true|false}. The positive class is
"allowed": precision = allowed queries that should be, recall = AI queries let through.
"""
import json
import time
from pathlib import Path

from .. import config
from ..intent import classify_intent
from . import metrics as M


def run_intent_eval(path: Path | None = None) -> dict:
    path = path or config.ROOT / "eval" / "intent_dataset.jsonl"
    items = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]

    tp = fp = fn = tn = errors = 0
    mistakes = []
    t0 = time.time()
    for item in items:
        intent = classify_intent(item["question"])
        if intent.category == "error":
            errors += 1
            mistakes.append({**item, "predicted": "error", "detail": intent.error})
            continue
        expected, got = item["allowed"], intent.allowed
        tp += expected and got
        tn += (not expected) and (not got)
        fp += (not expected) and got
        fn += expected and not got
        if expected != got:
            mistakes.append({**item, "predicted": intent.category})

    scored = tp + tn + fp + fn
    report = {
        "n": len(items),
        "errors": errors,
        "accuracy": (tp + tn) / scored if scored else 0.0,
        **M.classification_prf(tp, fp, fn),
        "false_allowed": fp,
        "false_blocked": fn,
        "seconds_per_query": round((time.time() - t0) / len(items), 2),
        "mistakes": mistakes,
    }
    print(f"\nIntent gate ({config.INTENT_MODEL}): {report['n']} queries, {errors} errors")
    for key in ("accuracy", "precision", "recall", "f1"):
        print(f"  {key:<18} {report[key]:.3f}")
    print(f"  {'false allowed':<18} {fp}\n  {'false blocked':<18} {fn}")
    print(f"  {'secs per query':<18} {report['seconds_per_query']}")
    for m in mistakes:
        print(f"  MISS expected_allowed={m['allowed']} got={m['predicted']}: {m['question']}")
    return report
