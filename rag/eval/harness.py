"""Experiment harness: run the eval for several pipeline variants and compare.

Experiments file (JSON):
{
  "defaults": {"n": 5, "ks": [1, 3, 5], "temperature": 0.7},
  "variants": [
    {"name": "baseline"},
    {"name": "top2", "top_k": 2},
    {"name": "mmr", "SEARCH_TYPE": "mmr"},
    {"name": "qwen-3b", "HF_LLM_MODEL": "Qwen/Qwen2.5-3B-Instruct"}
  ]
}

Lower-case keys (n, ks, temperature, top_k, limit, dataset) are run_eval
arguments; UPPER_CASE keys override rag.config settings for that variant.
"""
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .. import config
from .runner import print_report, run_eval

RUN_ARGS = {"n", "ks", "temperature", "top_k", "limit", "dataset"}

COLUMNS = [
    ("accuracy", lambda s: s["accuracy"]),
    ("pass@1", lambda s: s.get("pass@1")),
    ("pass@k", lambda s: _last(s, "pass@")),
    ("pass^k", lambda s: _last(s, "pass^")),
    ("ret_P", lambda s: s["retrieval"].get("precision_at_k")),
    ("ret_R", lambda s: s["retrieval"].get("recall_at_k")),
    ("MRR", lambda s: s["retrieval"].get("mrr")),
    ("tok_F1", lambda s: s["answer"]["token_f1"]),
    ("faithful", lambda s: s["truthfulness"]["faithfulness"]),
    ("halluc", lambda s: s["truthfulness"]["hallucination_rate"]),
    ("abst_F1", lambda s: s["abstention"]["f1"]),
    ("judge", lambda s: (s.get("llm_judge") or {}).get("judge_accuracy")),
    ("kappa", lambda s: (s.get("llm_judge") or {}).get("cohen_kappa")),
    ("secs", lambda s: s["config"]["seconds"]),
]


def _last(s: dict, prefix: str):
    keys = [k for k in s if k.startswith(prefix)]
    return s[max(keys, key=lambda k: int(k[len(prefix):]))] if keys else None


@contextmanager
def overrides(settings: dict):
    old = {}
    for key, value in settings.items():
        if not hasattr(config, key):
            raise KeyError(f"Unknown config setting: {key}")
        old[key] = getattr(config, key)
        setattr(config, key, value)
    try:
        yield
    finally:
        for key, value in old.items():
            setattr(config, key, value)


def run_experiments(path: Path, only: list[str] | None = None, verbose: bool = False) -> list[dict]:
    spec = json.loads(Path(path).read_text())
    defaults = spec.get("defaults", {})
    variants = [v for v in spec["variants"] if not only or v["name"] in only]
    if not variants:
        raise ValueError("No variants selected")

    results = []
    for v in variants:
        merged = {**defaults, **{k: val for k, val in v.items() if k != "name"}}
        args = {k: val for k, val in merged.items() if k in RUN_ARGS}
        settings = {k: val for k, val in merged.items() if k not in RUN_ARGS}
        if "ks" in args:
            args["ks"] = tuple(args["ks"])
        if "dataset" in args:
            args["dataset"] = Path(args["dataset"])

        print(f"\n=== {v['name']} {settings or ''} {args} ===")
        with overrides(settings):
            summary = run_eval(**args)
        summary["variant"] = v["name"]
        if verbose:
            print_report(summary)
        results.append(summary)

    print_comparison(results)
    out = config.EVAL_RESULTS_DIR / f"experiments-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=float))
    print(f"Saved comparison to {out}\n")
    return results


def print_comparison(results: list[dict]) -> None:
    name_w = max(8, *(len(r["variant"]) for r in results))
    header = f"{'variant':<{name_w}} " + " ".join(f"{c:>8}" for c, _ in COLUMNS)
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        cells = []
        for _, get in COLUMNS:
            try:
                v = get(r)
            except (KeyError, TypeError):
                v = None
            cells.append("     n/a" if v is None else f"{v:8.3f}" if isinstance(v, float) else f"{v:>8}")
        print(f"{r['variant']:<{name_w}} " + " ".join(cells))
    print()
