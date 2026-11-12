"""Measure the intent gate on labeled queries (eval/intent_dataset.jsonl).

Each line: {"question": "...", "allowed": true|false}. The positive class is
"allowed": precision = allowed queries that should be, recall = AI queries let through.
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
from pathlib import Path

from .. import config
from ..intent import classify_intent
from . import metrics as M
from .latency import fmt_stats, latency_stats


def run_intent_eval(path: Path | None = None) -> dict:
    path = path or config.ROOT / "eval" / "intent_dataset.jsonl"
    items = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]

    tp = fp = fn = tn = errors = 0
    mistakes = []
    t0 = time.time()
    lat = []
    for item in items:
        t1 = time.perf_counter()
        intent = classify_intent(item["question"])
        lat.append((time.perf_counter() - t1) * 1000)
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
        "latency_ms": latency_stats(lat),
        "mistakes": mistakes,
    }
    _lineaje_payload = f"\nIntent gate ({config.INTENT_MODEL}): {report['n']} queries, {errors} errors"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_intent_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:732985629701abaa210be476c12f15a8d8f0ffcbee2923e1cc5ac94c0a433227'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:732985629701abaa210be476c12f15a8d8f0ffcbee2923e1cc5ac94c0a433227', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/intent_eval.py', 'line': 52, 'function': 'run_intent_eval'}, 'file': 'rag/eval/intent_eval.py', 'line': 52, 'function': 'run_intent_eval', 'agent_name': 'run_intent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    for key in ("accuracy", "precision", "recall", "f1"):
        _lineaje_payload = f"  {key:<18} {report[key]:.3f}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_intent_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:ffc2f7612584029476c048096222d55071e0fdb396841e29703f91690ba4d977'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ffc2f7612584029476c048096222d55071e0fdb396841e29703f91690ba4d977', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/intent_eval.py', 'line': 54, 'function': 'run_intent_eval'}, 'file': 'rag/eval/intent_eval.py', 'line': 54, 'function': 'run_intent_eval', 'agent_name': 'run_intent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    _lineaje_payload = f"  {'false allowed':<18} {fp}\n  {'false blocked':<18} {fn}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_intent_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:ab7a800d11fc7737e3cf227c1a8d068120332d98fc4c17ee8dbeb6185a7ec708'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ab7a800d11fc7737e3cf227c1a8d068120332d98fc4c17ee8dbeb6185a7ec708', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/intent_eval.py', 'line': 55, 'function': 'run_intent_eval'}, 'file': 'rag/eval/intent_eval.py', 'line': 55, 'function': 'run_intent_eval', 'agent_name': 'run_intent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    _lineaje_payload = f"  {'latency':<18} {fmt_stats(report['latency_ms'])}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_intent_eval).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:699160d31f4a0e5ff3deaee5a5109ecd069f6e03e72ffb0c8084519bdaf163a3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:699160d31f4a0e5ff3deaee5a5109ecd069f6e03e72ffb0c8084519bdaf163a3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/intent_eval.py', 'line': 56, 'function': 'run_intent_eval'}, 'file': 'rag/eval/intent_eval.py', 'line': 56, 'function': 'run_intent_eval', 'agent_name': 'run_intent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    for m in mistakes:
        _lineaje_payload = f"  MISS expected_allowed={m['allowed']} got={m['predicted']}: {m['question']}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_intent_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9b385086afa666990db68eaac19472e2e24177aec194f32e9e5a24e8f62fec0f'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9b385086afa666990db68eaac19472e2e24177aec194f32e9e5a24e8f62fec0f', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/intent_eval.py', 'line': 58, 'function': 'run_intent_eval'}, 'file': 'rag/eval/intent_eval.py', 'line': 58, 'function': 'run_intent_eval', 'agent_name': 'run_intent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    # LINEAJE: runtime guardrail checks `report` as it flows from a tool to the user interface, before it leaves the application (in run_intent_eval).
    #   Detected: this statement moves data from a tool to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012, AI_DAT_SEC_027; sensitive values in `report` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:bbf058299a3ac2130ec7c72de85ca9bfe4229b2caef9ce0cf9e49aaa020c89e5'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:bbf058299a3ac2130ec7c72de85ca9bfe4229b2caef9ce0cf9e49aaa020c89e5', phase='data_egress', boundary={'source': 'tool_result', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='tool', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/intent_eval.py', 'line': 59, 'function': 'run_intent_eval'}, 'file': 'rag/eval/intent_eval.py', 'line': 59, 'function': 'run_intent_eval', 'agent_name': 'run_intent_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        report = _gr_client.enforce(_gr_site, report, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return report
