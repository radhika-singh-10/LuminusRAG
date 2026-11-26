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
    ("e2e_p50", lambda s: (s.get("latency") or {}).get("end_to_end_ms", {}).get("p50")),
    ("e2e_p95", lambda s: (s.get("latency") or {}).get("end_to_end_ms", {}).get("p95")),
    ("ttft_p50", lambda s: (s.get("latency") or {}).get("ttft_ms", {}).get("p50")),
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

        _lineaje_payload = f"\n=== {v['name']} {settings or ''} {args} ==="
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_experiments).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9698a7ec07900cd1e65ad21b8b8ce98c42a31769945a1c1266df9dfbacf0ad89'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9698a7ec07900cd1e65ad21b8b8ce98c42a31769945a1c1266df9dfbacf0ad89', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 85, 'function': 'run_experiments'}, 'file': 'rag/eval/harness.py', 'line': 85, 'function': 'run_experiments', 'agent_name': 'run_experiments', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        with overrides(settings):
            summary = run_eval(**args)
        summary["variant"] = v["name"]
        if verbose:
            print_report(summary)
        results.append(summary)

    print_comparison(results)
    out = config.EVAL_RESULTS_DIR / f"experiments-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # LINEAJE: runtime guardrail checks `results` as it flows from the agent to an external endpoint, before it leaves the application (in run_experiments).
    #   Detected: this statement moves data from the agent to an external endpoint with no runtime policy check (detection confidence: medium).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `results` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:5fdb26cc509e6f420fdb553ecf1a2ddef61efc27773551a890061f218a04764f'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5fdb26cc509e6f420fdb553ecf1a2ddef61efc27773551a890061f218a04764f', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'external_endpoint'}, fail_mode='ALLOW_WITH_AUDIT', source_type='agent', destination_type='external', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 96, 'function': 'run_experiments'}, 'file': 'rag/eval/harness.py', 'line': 96, 'function': 'run_experiments', 'agent_name': 'run_experiments', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        results = _gr_client.enforce(_gr_site, results, content_type='application/json', variable_name='results', source_file=__file__, before_line=96)
    except _gr_client.GuardrailUnavailableError:
        pass
    _lineaje_payload = json.dumps(results, indent=2, default=float)
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to a file, before it is written to disk (in run_experiments).
    #   Detected: this statement moves data from the agent to a file with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_025; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:05e0455e799a9710ff901107178bf5c86be3ebe8603f6561026232c40e9ca311'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:05e0455e799a9710ff901107178bf5c86be3ebe8603f6561026232c40e9ca311', phase='file_write', boundary={'source': 'agent_message', 'sink': 'file_content'}, fail_mode='BLOCK', source_type='agent', destination_type='file', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 96, 'function': 'run_experiments'}, 'file': 'rag/eval/harness.py', 'line': 96, 'function': 'run_experiments', 'agent_name': 'run_experiments', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=96)
    except _gr_client.GuardrailUnavailableError:
        pass
    out.write_text(_lineaje_payload)
    _lineaje_payload = f"Saved comparison to {out}\n"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_experiments).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:4f151cad0883bae3b551cac6511d541f8f3d4fe6958087af0cccbaee920e7c5c'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4f151cad0883bae3b551cac6511d541f8f3d4fe6958087af0cccbaee920e7c5c', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 97, 'function': 'run_experiments'}, 'file': 'rag/eval/harness.py', 'line': 97, 'function': 'run_experiments', 'agent_name': 'run_experiments', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    # LINEAJE: runtime guardrail checks `results` as it flows from the agent to the user interface, before it leaves the application (in run_experiments).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `results` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:5a591cfad6ed46f0584b350bf71ba6a9c8c05464a5d54089c531fd9b3345e801'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5a591cfad6ed46f0584b350bf71ba6a9c8c05464a5d54089c531fd9b3345e801', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 98, 'function': 'run_experiments'}, 'file': 'rag/eval/harness.py', 'line': 98, 'function': 'run_experiments', 'agent_name': 'run_experiments', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        results = _gr_client.enforce(_gr_site, results, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return results


def print_comparison(results: list[dict]) -> None:
    name_w = max(8, *(len(r["variant"]) for r in results))
    header = f"{'variant':<{name_w}} " + " ".join(f"{c:>8}" for c, _ in COLUMNS)
    _lineaje_payload = "\n" + header
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_comparison).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:197dea7add856a714ef2c09fddc7266aa5a30adb4b4be13132a130593a14847a'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:197dea7add856a714ef2c09fddc7266aa5a30adb4b4be13132a130593a14847a', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 104, 'function': 'print_comparison'}, 'file': 'rag/eval/harness.py', 'line': 104, 'function': 'print_comparison', 'agent_name': 'print_comparison', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = "-" * len(header)
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_comparison).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:2460768ebe2aa3c18b6c2b0e13bc599de3fef58ae9211823363f3b39bb0b8500'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2460768ebe2aa3c18b6c2b0e13bc599de3fef58ae9211823363f3b39bb0b8500', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 105, 'function': 'print_comparison'}, 'file': 'rag/eval/harness.py', 'line': 105, 'function': 'print_comparison', 'agent_name': 'print_comparison', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    for r in results:
        cells = []
        for _, get in COLUMNS:
            try:
                v = get(r)
            except (KeyError, TypeError, AttributeError):
                v = None
            cells.append("     n/a" if v is None else f"{v:8.3f}" if isinstance(v, float) else f"{v:>8}")
        _lineaje_payload = f"{r['variant']:<{name_w}} " + " ".join(cells)
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_comparison).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:98e63b45ae6ceac998cf2d4b3419b0fbb50c3c9bbf17f8fc195692b20b2af323'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:98e63b45ae6ceac998cf2d4b3419b0fbb50c3c9bbf17f8fc195692b20b2af323', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/harness.py', 'line': 114, 'function': 'print_comparison'}, 'file': 'rag/eval/harness.py', 'line': 114, 'function': 'print_comparison', 'agent_name': 'print_comparison', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    print()
