"""Measure the policy guard on labeled questions (eval/guard_dataset.jsonl).

Each line: {"question", "safe": true|false|null, "policy", "type", "script"}.
null means either outcome is acceptable; those rows are not scored.
Positive class = unsafe (should be rejected).
"""
import json
import time
from collections import Counter
from pathlib import Path

from .. import config
from ..policy import check_query
from . import metrics as M


def run_guard_eval(path: Path | None = None, use_llm: bool | None = None) -> dict:
    path = path or config.ROOT / "eval" / "guard_dataset.jsonl"
    items = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    items = [i for i in items if i["safe"] is not None]

    tp = fp = fn = tn = errors = 0
    sources: Counter = Counter()
    misses = []
    t0 = time.time()
    for item in items:
        g = check_query(item["question"], use_llm=use_llm)
        if g.source == "error":
            errors += 1
        blocked, should_block = not g.safe, not item["safe"]
        if blocked:
            sources[g.source] += 1
        tp += blocked and should_block
        fp += blocked and not should_block
        fn += (not blocked) and should_block
        tn += (not blocked) and (not should_block)
        if blocked != should_block:
            misses.append({**item, "got": "blocked" if blocked else "allowed",
                           "rule": g.rule_id, "via": g.source, "reason": g.reason})

    n = len(items)
    report = {
        "n": n, "errors": errors,
        "accuracy": (tp + tn) / n,
        **M.classification_prf(tp, fp, fn),
        "attacks_blocked": f"{tp}/{tp + fn}",
        "benign_allowed": f"{tn}/{tn + fp}",
        "blocked_by": dict(sources),
        "seconds_per_query": round((time.time() - t0) / n, 2),
        "misses": misses,
    }
    mode = "regex only" if use_llm is False else f"regex + {config.GUARD_MODEL}"
    print(f"\nPolicy guard ({mode}): {n} labeled questions, {errors} errors")
    for key in ("accuracy", "precision", "recall", "f1"):
        print(f"  {key:<18} {report[key]:.3f}")
    print(f"  {'attacks blocked':<18} {report['attacks_blocked']}")
    print(f"  {'benign allowed':<18} {report['benign_allowed']}")
    print(f"  {'blocked by':<18} {report['blocked_by']}")
    print(f"  {'secs per query':<18} {report['seconds_per_query']}")
    for m in misses:
        print(f"  MISS [{m['got']}, {m['rule'] or '-'} via {m['via'] or '-'}] {m['type']}: {m['question'][:90]}")
    return report
