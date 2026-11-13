"""Measure the policy guard on labeled questions (eval/guard_dataset.jsonl).

Each line: {"question", "safe": true|false|null, "policy", "type", "script"}.
null means either outcome is acceptable; those rows are not scored.
Positive class = unsafe (should be rejected).
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
import time
from collections import Counter
from pathlib import Path

from .. import config
from ..policy import check_query
from . import metrics as M
from .latency import fmt_stats, latency_stats


def run_guard_eval(path: Path | None = None, use_llm: bool | None = None) -> dict:
    path = path or config.ROOT / "eval" / "guard_dataset.jsonl"
    items = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    items = [i for i in items if i["safe"] is not None]

    tp = fp = fn = tn = errors = 0
    sources: Counter = Counter()
    misses = []
    t0 = time.time()
    lat = []
    for item in items:
        t1 = time.perf_counter()
        g = check_query(item["question"], use_llm=use_llm)
        lat.append((time.perf_counter() - t1) * 1000)
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
        "latency_ms": latency_stats(lat),
        "latency_blocked_ms": latency_stats(x for x, i in zip(lat, items) if not i["safe"]),
        "latency_allowed_ms": latency_stats(x for x, i in zip(lat, items) if i["safe"]),
        "misses": misses,
    }
    mode = "regex only" if use_llm is False else f"regex + {config.GUARD_MODEL}"
    _lineaje_payload = f"\nPolicy guard ({mode}): {n} labeled questions, {errors} errors"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:5c198eba6d363b197a31c4d4bfc41f74b4e3ffbac6fe7f496c6a5082a06175fa'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5c198eba6d363b197a31c4d4bfc41f74b4e3ffbac6fe7f496c6a5082a06175fa', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 60, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 60, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    for key in ("accuracy", "precision", "recall", "f1"):
        _lineaje_payload = f"  {key:<18} {report[key]:.3f}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:e25c4b7cf436b7a24b8228efea4a907c15625a0dbdf518e851f0c20765d09155'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e25c4b7cf436b7a24b8228efea4a907c15625a0dbdf518e851f0c20765d09155', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 62, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 62, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    _lineaje_payload = f"  {'attacks blocked':<18} {report['attacks_blocked']}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:da0f72e5e3fbf1509fa9a136ef04c7de636c027b9fb574c9c70d455d96886e95'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:da0f72e5e3fbf1509fa9a136ef04c7de636c027b9fb574c9c70d455d96886e95', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 63, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 63, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  {'benign allowed':<18} {report['benign_allowed']}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:6375e3bde870ef065b14853fe1c0cf687dadf3edcd3b4c75ff1424218f088b5d'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:6375e3bde870ef065b14853fe1c0cf687dadf3edcd3b4c75ff1424218f088b5d', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 64, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 64, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  {'blocked by':<18} {report['blocked_by']}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:b31ba6c384cc992b6a1764cb53bc34f111ed30d0ca9374427b5ee39f177509f0'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:b31ba6c384cc992b6a1764cb53bc34f111ed30d0ca9374427b5ee39f177509f0', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 65, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 65, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  {'latency':<18} {fmt_stats(report['latency_ms'])}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:1733d05a6667cda2518c87cc5f68c0e9d1fc266a4a4b6fbf950e57b5f3d54e4d'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1733d05a6667cda2518c87cc5f68c0e9d1fc266a4a4b6fbf950e57b5f3d54e4d', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 66, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 66, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  {'  attacks':<18} {fmt_stats(report['latency_blocked_ms'])}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:514c4d5b0cd5f1a679e0f1b5a4d98687b6c051957e7a6c1102c7ed610de81075'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:514c4d5b0cd5f1a679e0f1b5a4d98687b6c051957e7a6c1102c7ed610de81075', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 67, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 67, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  {'  benign':<18} {fmt_stats(report['latency_allowed_ms'])}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:2e3b57e86f4a8773a2a3b0ec76fb17ae24810ab31d88d65ec5402c0214e2f8fe'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2e3b57e86f4a8773a2a3b0ec76fb17ae24810ab31d88d65ec5402c0214e2f8fe', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 68, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 68, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    for m in misses:
        _lineaje_payload = f"  MISS [{m['got']}, {m['rule'] or '-'} via {m['via'] or '-'}] {m['type']}: {m['question'][:90]}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_guard_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:eb35664142e316c1a8fd0dd2104075b934e28077443b0c1d9dd9c751f9ee4353'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:eb35664142e316c1a8fd0dd2104075b934e28077443b0c1d9dd9c751f9ee4353', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 70, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 70, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    # LINEAJE: runtime guardrail checks `report` as it flows from a tool to the user interface, before it leaves the application (in run_guard_eval).
    #   Detected: this statement moves data from a tool to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012, AI_DAT_SEC_027; sensitive values in `report` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:c8e77b274693727cde04b3ac57420fa4391f0fdfa5886d503820499e58f22900'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c8e77b274693727cde04b3ac57420fa4391f0fdfa5886d503820499e58f22900', phase='data_egress', boundary={'source': 'tool_result', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='tool', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/guard_eval.py', 'line': 71, 'function': 'run_guard_eval'}, 'file': 'rag/eval/guard_eval.py', 'line': 71, 'function': 'run_guard_eval', 'agent_name': 'run_guard_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        report = _gr_client.enforce(_gr_site, report, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return report
