"""LuminusRAG CLI: python main.py ingest [--rebuild] | ask "question" | chat | add FILES | eval | bench | eval-intent | chats | summarize | eval-guard | eval-security | graph | gc | versions | chunks | agent | eval-agent | eval-ocr | ocr | watch | eval-chunking | traces | cache"""
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

import argparse
import sys
from pathlib import Path

from rag import config


def stream_answer(chain, question: str, history: list[dict] | None = None) -> dict:
    """Print status lines and the answer as it streams; return the final result."""
    result, streaming = None, False
    for event in chain.events(question, history):
        if event["type"] == "status" and sys.stdout.isatty():
            _lineaje_payload = f"\r\033[2K  … {event['message']}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in stream_answer).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:c78928165ee9faa7b100f9b985471e5f32fbed4f5ad4b216a1ef4f767ab76026'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c78928165ee9faa7b100f9b985471e5f32fbed4f5ad4b216a1ef4f767ab76026', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 14, 'function': 'stream_answer'}, 'file': 'main.py', 'line': 14, 'function': 'stream_answer', 'agent_name': 'stream_answer', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload, end="", flush=True)
        elif event["type"] == "token":
            if not streaming:
                _lineaje_payload = "\r\033[2K" if sys.stdout.isatty() else ""
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in stream_answer).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:2c3f49ea40379d7c6bd031314faaa95e602966e579b197206046babc3cba3a85'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2c3f49ea40379d7c6bd031314faaa95e602966e579b197206046babc3cba3a85', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 17, 'function': 'stream_answer'}, 'file': 'main.py', 'line': 17, 'function': 'stream_answer', 'agent_name': 'stream_answer', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload, end="")
                print()
                streaming = True
            _lineaje_payload = event["text"]
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in stream_answer).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:383d81729052531e489a68364bfbbb3ea3f95a9ebeb838a98e5a3bfcfa28f4da'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:383d81729052531e489a68364bfbbb3ea3f95a9ebeb838a98e5a3bfcfa28f4da', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 20, 'function': 'stream_answer'}, 'file': 'main.py', 'line': 20, 'function': 'stream_answer', 'agent_name': 'stream_answer', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload, end="", flush=True)
        elif event["type"] == "final":
            result = event["result"]
    _lineaje_payload = "\n"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in stream_answer).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:9811ebd6b1fef28e96769ac528b05e45002e895bb6823733e5749d9e0a19f6f3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9811ebd6b1fef28e96769ac528b05e45002e895bb6823733e5749d9e0a19f6f3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 23, 'function': 'stream_answer'}, 'file': 'main.py', 'line': 23, 'function': 'stream_answer', 'agent_name': 'stream_answer', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    # LINEAJE: runtime guardrail checks `result` as it flows from the agent to the user interface, before it leaves the application (in stream_answer).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `result` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:f112285b13d7dd4ca668007fd5964eb9d505a5563871f1dc0e566858938f6957'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:f112285b13d7dd4ca668007fd5964eb9d505a5563871f1dc0e566858938f6957', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 24, 'function': 'stream_answer'}, 'file': 'main.py', 'line': 24, 'function': 'stream_answer', 'agent_name': 'stream_answer', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        result = _gr_client.enforce(_gr_site, result, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return result


def print_result(result: dict, answer_shown: bool = False) -> None:
    intent = result.get("intent")
    tags = []
    if intent:
        tags.append(f"intent: {intent.category}")
    if result.get("origin"):
        tags.append(f"answered from: {result['origin']}")
    if tags:
        _lineaje_payload = f"\n[{' | '.join(tags)}]"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:8a822245cb1acdf93b2dfbc21cc7d1e837dc0c79e01280e812cb47f5ae6424dc'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:8a822245cb1acdf93b2dfbc21cc7d1e837dc0c79e01280e812cb47f5ae6424dc', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 35, 'function': 'print_result'}, 'file': 'main.py', 'line': 35, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    if result.get("standalone_question"):
        _lineaje_payload = f"[read as: {result['standalone_question']}]"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:4ed6944c227ef5a91ca8f71ee92b0d8902e8c033c3663e0edfc4e8b7752f114b'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4ed6944c227ef5a91ca8f71ee92b0d8902e8c033c3663e0edfc4e8b7752f114b', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 37, 'function': 'print_result'}, 'file': 'main.py', 'line': 37, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    if result.get("pii_redacted"):
        _lineaje_payload = f"[redacted before use: {', '.join(result['pii_redacted'])}]"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:d7abe61ddee7c95fd5ab91f8da66a1a240b2ff52d347f65d2ea11caf3412c614'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:d7abe61ddee7c95fd5ab91f8da66a1a240b2ff52d347f65d2ea11caf3412c614', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 39, 'function': 'print_result'}, 'file': 'main.py', 'line': 39, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    if result.get("web_error"):
        _lineaje_payload = f"[web search failed: {result['web_error']}]"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:77f8b1e41d56a9df689cbc0b574e3fb74ed7dff18d6c2a0a39c8d218f28bf819'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:77f8b1e41d56a9df689cbc0b574e3fb74ed7dff18d6c2a0a39c8d218f28bf819', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 41, 'function': 'print_result'}, 'file': 'main.py', 'line': 41, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    if result.get("stored"):
        _lineaje_payload = f"[saved {result['stored']} web passages to the knowledge base]"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:a5105eae09cd935bc13d7759f159ee18f1255d465ead8f6717d973a024f26654'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:a5105eae09cd935bc13d7759f159ee18f1255d465ead8f6717d973a024f26654', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 43, 'function': 'print_result'}, 'file': 'main.py', 'line': 43, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    if result.get("trace_id"):
        _lineaje_payload = f"[trace {result['trace_id'][:8]}: python main.py traces {result['trace_id'][:8]}]"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:e1cba7c4ee045bd5707f67a4c1ec0c9c67a8a1eea1c38d3b5d2bb5b43dc92ed6'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e1cba7c4ee045bd5707f67a4c1ec0c9c67a8a1eea1c38d3b5d2bb5b43dc92ed6', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 45, 'function': 'print_result'}, 'file': 'main.py', 'line': 45, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    if not answer_shown:
        _lineaje_payload = f"\n{result['answer']}\n"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:82982c0db7618e397d1efcebffa78fb22ac67ca1839af51b7b316489f493ce83'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:82982c0db7618e397d1efcebffa78fb22ac67ca1839af51b7b316489f493ce83', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 47, 'function': 'print_result'}, 'file': 'main.py', 'line': 47, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    if intent and intent.error and intent.category in ("error", "guard_error"):
        _lineaje_payload = f"[check failed: {intent.error}]\n"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:0d254ccd532d95c6a3bc2c3b0b011b329a352ac3fdd42cc30bdc2bc061e30c28'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0d254ccd532d95c6a3bc2c3b0b011b329a352ac3fdd42cc30bdc2bc061e30c28', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 49, 'function': 'print_result'}, 'file': 'main.py', 'line': 49, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload, file=sys.stderr)
    if not result["context"]:
        return
    _lineaje_payload = "Sources:"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:afe102ada4076817c35ad0dd5a33f3f5fb7c74956ef0a04da85736e037dccfae'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:afe102ada4076817c35ad0dd5a33f3f5fb7c74956ef0a04da85736e037dccfae', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 52, 'function': 'print_result'}, 'file': 'main.py', 'line': 52, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    for i, d in enumerate(result["context"], start=1):
        page = d.metadata.get("page")
        loc = f", page {page + 1}" if page is not None else ""
        title = f"{d.metadata['title']} — " if d.metadata.get("title") else ""
        _lineaje_payload = f"  [{i}] {title}{d.metadata.get('source', 'unknown')}{loc}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in print_result).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:02175505b0ec554802d34842ea153044a3e18f578a0765ee9cfb1497d2c58e48'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:02175505b0ec554802d34842ea153044a3e18f578a0765ee9cfb1497d2c58e48', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 57, 'function': 'print_result'}, 'file': 'main.py', 'line': 57, 'function': 'print_result', 'agent_name': 'print_result', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    print()


def show_traces(args) -> int:
    from rag import observability as obs

    if args.purge:
        _lineaje_payload = f"Removed {obs.purge()} traces older than {config.TRACE_RETENTION_DAYS} days."
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:bb8cfb0c036f69d1135d9aa9fa15b86a0cbc58c900d997e2ceb68276b98c0367'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:bb8cfb0c036f69d1135d9aa9fa15b86a0cbc58c900d997e2ceb68276b98c0367', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 65, 'function': 'show_traces'}, 'file': 'main.py', 'line': 65, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        return 0
    if args.stats:
        _lineaje_payload = f"{'span':<34}{'type':<11}{'count':>6}{'p50 ms':>9}{'p95 ms':>9}{'errors':>8}{'tokens':>9}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:a2ee523e349478351baad94ccc530568cc7547d253deba1133bb2ba4b9be91fa'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:a2ee523e349478351baad94ccc530568cc7547d253deba1133bb2ba4b9be91fa', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 68, 'function': 'show_traces'}, 'file': 'main.py', 'line': 68, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for r in obs.span_stats():
            _lineaje_payload = (f"{r['name'][:33]:<34}{r['type']:<11}{r['count']:>6}{r['p50_ms'] or 0:>9.0f}"
                  f"{r['p95_ms'] or 0:>9.0f}{r['error_rate']:>8.2f}{r['tokens'] or '':>9}")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:94735612b459b410223f86a3e34eb3da15155cefde034cf9d430163e53e3019b'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:94735612b459b410223f86a3e34eb3da15155cefde034cf9d430163e53e3019b', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 70, 'function': 'show_traces'}, 'file': 'main.py', 'line': 70, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        return 0
    if args.trace_id:
        t = obs.get_trace(args.trace_id)
        if not t:
            _lineaje_payload = f"No trace {args.trace_id}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:83ddfe23cee2d6578f033b85ecd840e0fbc230d4326a34202e55c9f9e84abe27'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:83ddfe23cee2d6578f033b85ecd840e0fbc230d4326a34202e55c9f9e84abe27', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 76, 'function': 'show_traces'}, 'file': 'main.py', 'line': 76, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            return 1
        _lineaje_payload = (f"{t['name']}  {t['trace_id']}  {t['latency_ms']} ms  {len(t['spans'])} spans  "
              f"{t['llm_calls']} LLM calls  {t['tokens'] or 0} tokens  status {t['status']}")
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:e12f95ec40937d00df6e6cf5884cf776fab479ccd9917a09d8566d362619f33e'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e12f95ec40937d00df6e6cf5884cf776fab479ccd9917a09d8566d362619f33e', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 78, 'function': 'show_traces'}, 'file': 'main.py', 'line': 78, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        _lineaje_payload = f"question: {t['question']}\n"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:c6b2048fe80188a28e9083414e7d0c93270f0af86e7097f3effb0c46402c742d'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c6b2048fe80188a28e9083414e7d0c93270f0af86e7097f3effb0c46402c742d', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 80, 'function': 'show_traces'}, 'file': 'main.py', 'line': 80, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for sp in t["spans"]:
            llm = (f"  {sp['model']} in={sp['tokens_in']} out={sp['tokens_out']}"
                   if sp["run_type"] in ("llm", "chat_model") else "")
            err = f"  ERROR {sp['error'][:80]}" if sp["error"] else ""
            _lineaje_payload = f"{'  ' * sp['depth']}{sp['name']} [{sp['run_type']}] {sp['latency_ms']} ms{llm}{err}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:1c7506f34998fb81a23e7c49b41abb8a2aa217ec93d683761d79a253d506a7ae'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1c7506f34998fb81a23e7c49b41abb8a2aa217ec93d683761d79a253d506a7ae', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 85, 'function': 'show_traces'}, 'file': 'main.py', 'line': 85, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        return 0
    rows = obs.list_traces(args.limit, args.chat)
    if not rows:
        _lineaje_payload = "No traces yet."
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:212b01c359384c24488769950d6c572a1cb4156e22f798d1986a2149fcbfc8d8'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:212b01c359384c24488769950d6c572a1cb4156e22f798d1986a2149fcbfc8d8', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 89, 'function': 'show_traces'}, 'file': 'main.py', 'line': 89, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    for r in rows:
        _lineaje_payload = (f"{(r['start'] or '')[:19].replace('T', ' ')}  {r['trace_id'][:8]}  {r['name']:<17} "
              f"{r['latency_ms'] or 0:>6} ms  {r['spans']:>3} spans  {r['llm_calls']:>2} LLM  "
              f"{r['status']:<5}  {(r['question'] or '')[:60]}")
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in show_traces).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:e847f8782d098275ef9dab0bc7b163771a442498e9dfe0f55b69e6c176c47aec'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e847f8782d098275ef9dab0bc7b163771a442498e9dfe0f55b69e6c176c47aec', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 91, 'function': 'show_traces'}, 'file': 'main.py', 'line': 91, 'function': 'show_traces', 'agent_name': 'show_traces', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
    return 0


def watch_loop(quiet: float | None) -> int:
    """Re-index changed files once data/ has been quiet for DEBOUNCE_SECONDS."""
    from rag.versioning import wait_for_gc
    from rag.watcher import Watcher

    def on_event(event: str, info: dict) -> None:
        name = Path(info.get("path") or info.get("source") or "").name
        if event == "change":
            _lineaje_payload = (f"  {info['kind']:<8} {name}  ({info['pending']} pending; "
                  f"sync in {info['sync_in']:.0f}s unless more changes)")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in on_event).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:4c77d5ea0a86cf280c81ba7cf47024da3ecc0bcfcf1c5353327642ffd787cf9f'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4c77d5ea0a86cf280c81ba7cf47024da3ecc0bcfcf1c5353327642ffd787cf9f', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 105, 'function': 'watch_loop.on_event'}, 'file': 'main.py', 'line': 105, 'function': 'on_event', 'agent_name': 'on_event', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        elif event == "sync_start":
            _lineaje_payload = f"Quiet for {w.debouncer.quiet:g}s -> syncing {len(info['files'])} file(s)"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in on_event).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:ca844cd4aa51292fa83e04468b6300f293274d190c372af273ddcbfef22e28c0'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ca844cd4aa51292fa83e04468b6300f293274d190c372af273ddcbfef22e28c0', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 108, 'function': 'watch_loop.on_event'}, 'file': 'main.py', 'line': 108, 'function': 'on_event', 'agent_name': 'on_event', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        elif event == "diff":
            _lineaje_payload = (f"  diff {name}: {info['total']} chunks, {info['unchanged']} unchanged, "
                  f"{info['added']} new/changed, {info['removed']} removed")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in on_event).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:959b89c309fbbbcc2751637e0fc6020e707006f35e465eab7bb17b4e0e40bacf'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:959b89c309fbbbcc2751637e0fc6020e707006f35e465eab7bb17b4e0e40bacf', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 110, 'function': 'watch_loop.on_event'}, 'file': 'main.py', 'line': 110, 'function': 'on_event', 'agent_name': 'on_event', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        elif event == "activated":
            _lineaje_payload = f"  {name}: version {info['version']} live"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in on_event).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:c2ce025ffb5be9b2d5a331d6cd78a11b0fbb310ab108e10056a6b9d1185522b3'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c2ce025ffb5be9b2d5a331d6cd78a11b0fbb310ab108e10056a6b9d1185522b3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 113, 'function': 'watch_loop.on_event'}, 'file': 'main.py', 'line': 113, 'function': 'on_event', 'agent_name': 'on_event', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        elif event == "removed":
            _lineaje_payload = f"  {name}: deleted, retired"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in on_event).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:a8da86b263e90fa5bbeb56853ac0904cf782a25d48afe82870150eda1d772e18'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:a8da86b263e90fa5bbeb56853ac0904cf782a25d48afe82870150eda1d772e18', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 115, 'function': 'watch_loop.on_event'}, 'file': 'main.py', 'line': 115, 'function': 'on_event', 'agent_name': 'on_event', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        elif event == "sync_done":
            s = info["stats"]
            _lineaje_payload = (f"Synced in {info['seconds']}s: {s['chunks_written']} chunks embedded, "
                  f"{s['chunks_reused']} reused\n")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in on_event).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:247005de23bf6539579b5096978c431a1b42c034a46686a6391b23706b409217'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:247005de23bf6539579b5096978c431a1b42c034a46686a6391b23706b409217', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 118, 'function': 'watch_loop.on_event'}, 'file': 'main.py', 'line': 118, 'function': 'on_event', 'agent_name': 'on_event', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        elif event == "sync_error":
            _lineaje_payload = f"Sync failed: {info['error']}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in on_event).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:df483afbaf208568550269c921033b472624982c71c63ca1dcbfb010cdef8376'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:df483afbaf208568550269c921033b472624982c71c63ca1dcbfb010cdef8376', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 121, 'function': 'watch_loop.on_event'}, 'file': 'main.py', 'line': 121, 'function': 'on_event', 'agent_name': 'on_event', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)

    w = Watcher(quiet=quiet, on_event=on_event)
    _lineaje_payload = (f"Watching {w.data_dir} (debounce {w.debouncer.quiet:g}s, max wait "
          f"{w.debouncer.max_wait:g}s). Ctrl+C to stop.")
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in watch_loop).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:1f0c0d9b3c325c1b775fd6b8f27ad2140e5289b6b1ed047d8c8e36db17fcf2e9'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1f0c0d9b3c325c1b775fd6b8f27ad2140e5289b6b1ed047d8c8e36db17fcf2e9', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 124, 'function': 'watch_loop'}, 'file': 'main.py', 'line': 124, 'function': 'watch_loop', 'agent_name': 'watch_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    try:
        w.run()
    except KeyboardInterrupt:
        pass
    wait_for_gc()
    return 0


def agent_loop(chat_id: str | None, user_id: str, show_trace: bool) -> int:
    """Interactive multi-step session: type a question, or 1-3 to take a suggestion."""
    from rag.agent.harness import build_agent
    from rag.history import new_chat_id
    from rag.prompt_cache import warm_in_background

    warm_in_background()  # prefill the system prompts while the user types

    agent = build_agent(user_id=user_id)
    chat_id = chat_id or new_chat_id()
    _lineaje_payload = (f"Chat {chat_id}: up to {agent.max_steps} questions. Type a question, "
          f"a number to take a suggested follow-up, or 'quit'.\n")
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:11124f75506ffcbe76a563e5e44b87887453206fd1242a22afaf7530f4b087cf'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:11124f75506ffcbe76a563e5e44b87887453206fd1242a22afaf7530f4b087cf', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 144, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 144, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    followups: list[dict] = []
    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.lower() in {"quit", "exit", "q"}:
            return 0
        if not line:
            continue
        from_fu = line.isdigit() and 1 <= int(line) <= len(followups)
        question = followups[int(line) - 1]["question"] if from_fu else line
        if from_fu:
            _lineaje_payload = f"   → {question}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:e76e5c8ec758f4e1ca7ca6c0a996dd072044583414baa1174af4212b2e5fa541'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e76e5c8ec758f4e1ca7ca6c0a996dd072044583414baa1174af4212b2e5fa541', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 160, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 160, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        result = stream_answer(_AgentEvents(agent, chat_id, from_fu), question)
        print_result(result, answer_shown=True)
        if result.get("interests"):
            _lineaje_payload = "[interests: " + ", ".join(i["name"] for i in result["interests"][:5]) + "]"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:6e55e0f34c130f1d7b01951f9cf70f23c2520755fb7d917cbc659be7469e6a26'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:6e55e0f34c130f1d7b01951f9cf70f23c2520755fb7d917cbc659be7469e6a26', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 164, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 164, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        if show_trace:
            for t in result["trace"]:
                _lineaje_payload = f"  · {t['layer']:<15} {t['tool']:<18} {t['ms']:>6} ms  {t.get('note', '')}"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:e67ff10e8d04b1f6a49ba337af4fe5dcecfceb3fe74bf426185e8f0083bdc015'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e67ff10e8d04b1f6a49ba337af4fe5dcecfceb3fe74bf426185e8f0083bdc015', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 167, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 167, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
        _lineaje_payload = f"[step {result['step']}/{result['max_steps']}]"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:00bec07f6926ea8a1dc6f5c122c3a197c6023b35d07aa34a8a567a2ee34100e1'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:00bec07f6926ea8a1dc6f5c122c3a197c6023b35d07aa34a8a567a2ee34100e1', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 168, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 168, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        followups = result["followups"]
        for i, f in enumerate(followups, 1):
            _lineaje_payload = f"  {i}. {f['question']}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:3d2b47445358533079052c5aec3fc775cbdfbd4dac2cb4eeadcc847fa2c75be8'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:3d2b47445358533079052c5aec3fc775cbdfbd4dac2cb4eeadcc847fa2c75be8', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 171, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 171, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        if result.get("closed"):
            if result.get("summary"):
                _lineaje_payload = f"\nConversation summary:\n{result['summary']}"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:a2b7b354e44c71f56f0035395e380ce9981fb73aaf77498e20ea3d9403a1a109'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:a2b7b354e44c71f56f0035395e380ce9981fb73aaf77498e20ea3d9403a1a109', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 174, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 174, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
            _lineaje_payload = "\nThis conversation is complete. Start a new one with: python main.py agent"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in agent_loop).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:845d912ed28fd3220c9caf9459512edccd4432dac2c8f2aaf90917504582fe79'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:845d912ed28fd3220c9caf9459512edccd4432dac2c8f2aaf90917504582fe79', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 142, 'name': 'agent'}, 'invocation': {'file': 'main.py', 'line': 175, 'function': 'agent_loop'}, 'file': 'main.py', 'line': 175, 'function': 'agent_loop', 'agent_name': 'agent_loop', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            return 0
        print()


class _AgentEvents:
    """Adapts the harness to stream_answer's chain.events(question, history) call."""

    def __init__(self, agent, chat_id: str, from_followup: bool):
        self.agent, self.chat_id, self.from_followup = agent, chat_id, from_followup

    def events(self, question: str, history=None):
        return self.agent.events(self.chat_id, question, self.from_followup)


def main() -> int:
    parser = argparse.ArgumentParser(description="LuminusRAG: guarded GraphRAG for AI questions")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help=f"Sync the index with files in {config.DATA_DIR}")
    ing.add_argument("--rebuild", action="store_true", help="Drop and rebuild the index")
    add = sub.add_parser("add", help="Add .pdf/.txt/.md or source-code files to the knowledge base")
    add.add_argument("files", nargs="+", type=Path)
    sub.add_parser("docs", help="List indexed documents")
    ask = sub.add_parser("ask", help="Ask a single question")
    ask.add_argument("question")
    sub.add_parser("chat", help="Interactive Q&A loop")
    ev = sub.add_parser("eval", help="Evaluate the pipeline on a labeled dataset")
    ev.add_argument("--dataset", type=Path, default=config.EVAL_DATASET)
    ev.add_argument("-n", type=int, default=5, help="Samples per question (for pass@k)")
    ev.add_argument("-k", default="1,3,5", help="Comma-separated k values for pass@k / pass^k")
    ev.add_argument("--temperature", type=float, default=0.7)
    ev.add_argument("--top-k", type=int, default=None, help="Chunks to retrieve")
    ev.add_argument("--limit", type=int, default=None, help="Only the first N questions")
    gr = sub.add_parser("graph", help="Knowledge graph: build, stats, or show an entity")
    gr.add_argument("action", choices=["build", "rebuild", "stats", "show"])
    gr.add_argument("entity", nargs="?", help="Entity name for 'show'")
    sub.add_parser("gc", help="Garbage-collect retired document versions now")
    sub.add_parser("versions", help="Show document versions and registry state")
    ch = sub.add_parser("chunks", help="Show the active chunks of a file")
    ch.add_argument("file")
    sub.add_parser("chats", help="List saved chats")
    summ = sub.add_parser("summarize", help="Summarize each saved chat with the local LLM")
    summ.add_argument("chat_id", nargs="?", help="One chat id (default: every chat)")
    summ.add_argument("--limit", type=int, default=None, help="Only the N most recent chats")
    summ.add_argument("--overview", action="store_true", help="Also combine into one overview")
    es = sub.add_parser("eval-security", help="Full-pipeline security eval: PII and prompt injection")
    es.add_argument("-n", type=int, default=3, help="Samples per case (for pass@k)")
    es.add_argument("-k", default="1,3", help="Comma-separated k values")
    es.add_argument("--temperature", type=float, default=0.7)
    es.add_argument("--limit", type=int, default=None)
    eg = sub.add_parser("eval-guard", help="Measure the policy guard on labeled attack/benign questions")
    eg.add_argument("--no-llm", action="store_true", help="Regex rules only")
    sub.add_parser("eval-intent", help="Measure the Ollama intent gate on labeled queries")
    ag = sub.add_parser("agent", help="Multi-step agent chat with follow-up suggestions (max 10 steps)")
    ag.add_argument("--chat", default=None, help="Continue a saved chat id")
    ag.add_argument("--user", default="local", help="User id for the interest profile")
    ag.add_argument("--trace", action="store_true", help="Print the tool trace per turn")
    ea = sub.add_parser("eval-agent", help="Evaluate personalization and multi-step follow-up sessions")
    ea.add_argument("--steps", type=int, default=None, help="Steps per session (default AGENT_MAX_STEPS)")
    ea.add_argument("--limit", type=int, default=None, help="Only the first N sessions")
    ea.add_argument("--compare", action="store_true", help="Also run sessions with personalization off")
    ea.add_argument("--no-sessions", action="store_true", help="Personalized retrieval only")
    ea.add_argument("--no-retrieval", action="store_true", help="Sessions only")
    wa = sub.add_parser("watch", help="Watch data/ and re-index changed files after a quiet period")
    wa.add_argument("--quiet", type=float, default=None,
                    help=f"Seconds without changes before syncing (default {config.DEBOUNCE_SECONDS:g})")
    sub.add_parser("eval-chunking", help="Chunking checks (no overlap, exact partition) + code retrieval eval")
    tr = sub.add_parser("traces", help="Observability: list traces, show one as a span tree, or stats")
    tr.add_argument("trace_id", nargs="?", help="Trace id (or prefix) to show")
    tr.add_argument("--stats", action="store_true", help="Latency / errors / tokens by span name")
    tr.add_argument("--chat", default=None, help="Only traces of this chat id")
    tr.add_argument("--limit", type=int, default=20)
    tr.add_argument("--purge", action="store_true", help="Delete traces older than TRACE_RETENTION_DAYS")
    ca = sub.add_parser("cache", help="Prompt cache: prefill system prompts (warm) or show hit rates")
    ca.add_argument("action", choices=["warm", "status"])
    sub.add_parser("eval-ocr", help="OCR accuracy (CER/WER) and retrieval on synthetic scanned PDFs")
    oc = sub.add_parser("ocr", help="OCR a PDF and print the text of its scanned pages")
    oc.add_argument("file", type=Path)
    oc.add_argument("--all", action="store_true", help="OCR every page, not only pages without text")
    bench = sub.add_parser("bench", help="Run and compare eval variants from an experiments file")
    bench.add_argument("--config", type=Path, default=config.ROOT / "eval" / "experiments.json")
    bench.add_argument("--only", default=None, help="Comma-separated variant names")
    bench.add_argument("-v", "--verbose", action="store_true", help="Full report per variant")

    args = parser.parse_args()

    if args.cmd == "ingest":
        from rag.ingest import ingest

        from rag.versioning import wait_for_gc

        ingest(rebuild=args.rebuild)
        wait_for_gc()  # the background GC must finish before this process exits
        return 0

    if args.cmd == "cache":
        if args.action == "warm":
            from rag.prompt_cache import warm

            for name, r in warm().items():
                _lineaje_payload = (f"{name:<42} " + (r["error"] if "error" in r else
                      f"{r['prompt_tokens']} tokens, prompt {r['prompt_ms']} ms, load {r['load_ms']} ms"))
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:72c2e644ba04e7a586e164c2846e319e9b9073c133a1ee0cf45c16a9744d3895'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:72c2e644ba04e7a586e164c2846e319e9b9073c133a1ee0cf45c16a9744d3895', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 276, 'function': 'main'}, 'file': 'main.py', 'line': 276, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
            return 0
        from rag import observability as obs

        rows = [r for r in obs.span_stats() if r.get("cache_hit_rate") is not None]
        if not rows:
            _lineaje_payload = "No Ollama calls traced yet."
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:04391987ab3b3f7abeba8179c14e401b43120a461b596f12963912b87aa4f62a'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:04391987ab3b3f7abeba8179c14e401b43120a461b596f12963912b87aa4f62a', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 283, 'function': 'main'}, 'file': 'main.py', 'line': 283, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        for r in sorted(rows, key=lambda r: r["name"]):
            _lineaje_payload = (f"{r['name']:<16} {r['count']:>5} calls  cache hit rate {r['cache_hit_rate']:.2f}  "
                  f"prompt p50 {r['prompt_ms_p50'] or 0:.0f} ms")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:ae0be1ee25af5e11a916305bcdb5df120d6b98ce513ec9de75943b29c0f91aac'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ae0be1ee25af5e11a916305bcdb5df120d6b98ce513ec9de75943b29c0f91aac', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 285, 'function': 'main'}, 'file': 'main.py', 'line': 285, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        return 0

    if args.cmd == "traces":
        return show_traces(args)

    if args.cmd == "watch":
        return watch_loop(args.quiet)

    if args.cmd == "eval-chunking":
        from rag.eval.chunk_eval import run_chunk_eval

        out = run_chunk_eval()
        _lineaje_payload = f"\nSaved to {out['path']}  ({out['seconds']}s)"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:3c1664947354444367a1c36ebf394ccf666b50287c6d9edb7fea1d3b708fd958'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:3c1664947354444367a1c36ebf394ccf666b50287c6d9edb7fea1d3b708fd958', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 299, 'function': 'main'}, 'file': 'main.py', 'line': 299, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        return 0

    if args.cmd == "eval-ocr":
        from rag.eval.ocr_eval import run_ocr_eval

        out = run_ocr_eval()
        _lineaje_payload = f"\nSaved to {out['path']}  ({out['seconds']}s)"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:e1a3cc310bf90a0a0726de9811317d09cc0737d7ee22f3a1c45afc4c2daeeea7'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e1a3cc310bf90a0a0726de9811317d09cc0737d7ee22f3a1c45afc4c2daeeea7', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 306, 'function': 'main'}, 'file': 'main.py', 'line': 306, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        return 0

    if args.cmd == "ocr":
        from langchain_community.document_loaders import PyPDFLoader

        from rag.ocr import needs_ocr, ocr_pdf_pages

        pages = PyPDFLoader(str(args.file)).load()
        # LINEAJE: runtime guardrail checks `pages` as it flows from a data source to the RAG pipeline, after the tool returns (in main).
        #   Detected: this statement moves data from a data source to the RAG pipeline with no runtime policy check (detection confidence: medium).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `pages` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:1cb3ccc947b9a2af584016dafb8aabfdace6d60eea04c7230bc69d1811d2b9db'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1cb3ccc947b9a2af584016dafb8aabfdace6d60eea04c7230bc69d1811d2b9db', phase='post_tool', boundary={'source': 'data_source', 'sink': 'rag_pipeline'}, fail_mode='ALLOW_WITH_AUDIT', source_type='data_source', destination_type='rag_pipeline', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 314, 'function': 'main'}, 'file': 'main.py', 'line': 314, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            pages = _gr_client.enforce(_gr_site, pages, content_type='application/json', variable_name='pages', source_file=__file__, before_line=314)
        except _gr_client.GuardrailUnavailableError:
            pass
        todo = [i for i, d in enumerate(pages) if args.all or needs_ocr(d.page_content)]
        if not todo:
            _lineaje_payload = f"All {len(pages)} pages have a text layer; nothing to OCR (use --all to force)."
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:cd65d37eb17df31b69866b1a1e4a8dc8b94a4483d876f452749d2513e25b2b10'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:cd65d37eb17df31b69866b1a1e4a8dc8b94a4483d876f452749d2513e25b2b10', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 317, 'function': 'main'}, 'file': 'main.py', 'line': 317, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            return 0
        for i, r in ocr_pdf_pages(args.file, todo).items():
            conf = f"{r.confidence:.2f}" if r.confidence is not None else "n/a"
            _lineaje_payload = f"--- page {i + 1} (OCR, {r.lines} lines, confidence {conf}, {r.seconds:.1f}s) ---"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:64707063f4bfcde28c453e3878c8e0e778fd884bb804ff6450aaf6ef427066c5'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:64707063f4bfcde28c453e3878c8e0e778fd884bb804ff6450aaf6ef427066c5', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 321, 'function': 'main'}, 'file': 'main.py', 'line': 321, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            _lineaje_payload = r.text or "[no text found]"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:4e469d5bf12c7cabe1c86ec267fbc5f6c4c72fb8c9a361bd9e45a3ff966788bc'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4e469d5bf12c7cabe1c86ec267fbc5f6c4c72fb8c9a361bd9e45a3ff966788bc', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 322, 'function': 'main'}, 'file': 'main.py', 'line': 322, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        return 0

    if args.cmd == "eval-agent":
        from rag.eval.agent_eval import print_agent_report, run_agent_eval

        print_agent_report(run_agent_eval(sessions=not args.no_sessions, retrieval=not args.no_retrieval,
                                          compare=args.compare, steps=args.steps, limit=args.limit))
        return 0

    if args.cmd == "agent":
        return agent_loop(args.chat, args.user, args.trace)

    if args.cmd == "gc":
        from rag.versioning import collect_garbage

        _lineaje_payload = collect_garbage(grace_seconds=0)
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:38c628b7a1a90622dd9a4ae287fb7ee0f909a0cd0578a63f6c5c9ee9acaed7ff'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:38c628b7a1a90622dd9a4ae287fb7ee0f909a0cd0578a63f6c5c9ee9acaed7ff', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 338, 'function': 'main'}, 'file': 'main.py', 'line': 338, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        return 0

    if args.cmd == "versions":
        from rag import versioning as V

        _lineaje_payload = V.registry_stats()
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:01dfd05ea82c969a66e0e4f049783026cfee21848d77f1438a68bd803863d582'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:01dfd05ea82c969a66e0e4f049783026cfee21848d77f1438a68bd803863d582', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 344, 'function': 'main'}, 'file': 'main.py', 'line': 344, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for d in sorted(V.documents(), key=lambda d: d["source"]):
            _lineaje_payload = f"\n{Path(d['source']).name}  ({d['doc_id']}, active v{d['active_version']}, {d['chunks']} chunks)"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:57c6bb28c8b174c9686a8fbc3c66c00a1c4d7001123927b539f94f5e41edcc8a'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:57c6bb28c8b174c9686a8fbc3c66c00a1c4d7001123927b539f94f5e41edcc8a', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 346, 'function': 'main'}, 'file': 'main.py', 'line': 346, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            for h in V.history(d["doc_id"]):
                _lineaje_payload = f"  v{h['version']:<3} {h['status']:<9} {h['chunks']:>3} chunks  {h['created']}"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:dc59fdcf8315e44b53b0107e7fe97769e6ad256d968f189baf432220aa1a496f'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:dc59fdcf8315e44b53b0107e7fe97769e6ad256d968f189baf432220aa1a496f', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 348, 'function': 'main'}, 'file': 'main.py', 'line': 348, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
        return 0

    if args.cmd == "chunks":
        from rag.ingest import get_chunks

        for c in get_chunks(str(Path(args.file).resolve())):
            _lineaje_payload = f"[{c['index']}] {c['chunk_id'][:14]}  {c['heading'] or '-'}  ({len(c['text'])} chars)"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:4d8184e1706784b603b01405d60045d2ab39c2f994a9ee21ddb1960416733cf4'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4d8184e1706784b603b01405d60045d2ab39c2f994a9ee21ddb1960416733cf4', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 355, 'function': 'main'}, 'file': 'main.py', 'line': 355, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        return 0

    if args.cmd == "graph":
        from rag.graph import graph_context, graph_stats, update_graph

        if args.action in ("build", "rebuild"):
            update_graph(rebuild=args.action == "rebuild",
                         progress=lambda i, n: print(f"\r  extracting {i}/{n}", end="", flush=True))
            print()
        elif args.action == "stats":
            st_ = graph_stats()
            _lineaje_payload = f"{st_['nodes']} entities, {st_['edges']} relations from {st_['chunks']} chunks"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:639a79071c5afef2621378a93e8db22d184527e0d4808dcd58d94b089c520f1a'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:639a79071c5afef2621378a93e8db22d184527e0d4808dcd58d94b089c520f1a', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 367, 'function': 'main'}, 'file': 'main.py', 'line': 367, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            for name, etype, deg in st_["top"]:
                _lineaje_payload = f"  {deg:>3}  {name} ({etype})"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:5578b889e3779523f39a8c50222f275337d166c2aaede322ee5ea81050d22830'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5578b889e3779523f39a8c50222f275337d166c2aaede322ee5ea81050d22830', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 369, 'function': 'main'}, 'file': 'main.py', 'line': 369, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
        else:
            seeds, facts, chunks = graph_context(args.entity or "")
            _lineaje_payload = f"Matched: {', '.join(seeds) or 'nothing'}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:cd80d510920d06f45c5e6f4a6adac4150c43c30acee8093ac21d744ee42f80f4'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:cd80d510920d06f45c5e6f4a6adac4150c43c30acee8093ac21d744ee42f80f4', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 372, 'function': 'main'}, 'file': 'main.py', 'line': 372, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            for f_ in facts:
                _lineaje_payload = f"  {f_}"
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:36447ef3290d6789ccf12259c4c5ce029f9c833d83bd375f31c7991d98bbaf59'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:36447ef3290d6789ccf12259c4c5ce029f9c833d83bd375f31c7991d98bbaf59', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 374, 'function': 'main'}, 'file': 'main.py', 'line': 374, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
        return 0

    if args.cmd == "chats":
        from rag.history import list_chats

        chats = list_chats()
        if not chats:
            _lineaje_payload = "No saved chats yet."
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:4d1bc9e82bed164755377d66f16dbc1ef4279efc735c71ea4d86acad8c2fb539'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4d1bc9e82bed164755377d66f16dbc1ef4279efc735c71ea4d86acad8c2fb539', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 382, 'function': 'main'}, 'file': 'main.py', 'line': 382, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        for c in chats:
            mark = " (summarized)" if c["has_summary"] else ""
            _lineaje_payload = (f"  {c['id']}  {c['updated'][:16].replace('T', ' ')}  "
                  f"{c['n_messages'] // 2:>3} questions  {c['title']}{mark}")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:c34918adbbb7773088bb5dedadb40779e5486d0fdfb399af73d55d3135ab4881'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c34918adbbb7773088bb5dedadb40779e5486d0fdfb399af73d55d3135ab4881', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 385, 'function': 'main'}, 'file': 'main.py', 'line': 385, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        return 0

    if args.cmd == "summarize":
        from rag.chain import get_llm
        from rag.history import summarize_all, summarize_chat, summarize_each

        llm = get_llm()
        if args.chat_id:
            _lineaje_payload = f"\n{summarize_chat(args.chat_id, llm)}\n"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:6e941ed569a125e6324fc5ee0d26becd3eaac30de1626ffd964a33d1d6b69bb3'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:6e941ed569a125e6324fc5ee0d26becd3eaac30de1626ffd964a33d1d6b69bb3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 395, 'function': 'main'}, 'file': 'main.py', 'line': 395, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            return 0
        progress = lambda i, n, t: print(f"  summarizing {i}/{n}: {t}", file=sys.stderr)  # noqa: E731
        if args.overview:
            result = summarize_all(llm, limit=args.limit or 10, progress=progress)
            chats, overview = result["chats"], result["overview"]
        else:
            chats, overview = summarize_each(llm, limit=args.limit, progress=progress), None
        for c in chats:
            _lineaje_payload = f"\n=== {c['title']}  ({c['id']}, {c['updated'][:16].replace('T', ' ')})"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:bdbd8db1fbb613dad459f12c405be8087a6d5b815e64e2bf8cdab1dc8a461a98'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:bdbd8db1fbb613dad459f12c405be8087a6d5b815e64e2bf8cdab1dc8a461a98', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 404, 'function': 'main'}, 'file': 'main.py', 'line': 404, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            _lineaje_payload = c["summary"]
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:552d8b8bcdbe14f0437f3fb3c741e2e927aaa60bb11db400cf786563b8ef8ac3'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:552d8b8bcdbe14f0437f3fb3c741e2e927aaa60bb11db400cf786563b8ef8ac3', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 405, 'function': 'main'}, 'file': 'main.py', 'line': 405, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        if overview:
            _lineaje_payload = f"\n=== Overview of all chats\n{overview}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:13de52cc758ebb0a2d3a458c7cc8c3275ef75f7a034d6cd010b6e886e9af25cd'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:13de52cc758ebb0a2d3a458c7cc8c3275ef75f7a034d6cd010b6e886e9af25cd', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 407, 'function': 'main'}, 'file': 'main.py', 'line': 407, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        print()
        return 0

    if args.cmd == "eval-security":
        from rag.eval.security_eval import print_security_report, run_security_eval

        summary = run_security_eval(n=args.n, ks=tuple(int(k) for k in args.k.split(",")),
                                    temperature=args.temperature, limit=args.limit)
        print_security_report(summary)
        return 0

    if args.cmd == "eval-guard":
        from rag.eval.guard_eval import run_guard_eval

        run_guard_eval(use_llm=False if args.no_llm else None)
        return 0

    if args.cmd == "eval-intent":
        from rag.eval.intent_eval import run_intent_eval

        run_intent_eval()
        return 0

    if args.cmd == "add":
        from rag.ingest import add_files

        from rag.versioning import wait_for_gc

        add_files(args.files)
        wait_for_gc()
        return 0

    if args.cmd == "docs":
        from rag.ingest import list_indexed

        for d in list_indexed():
            pages = f", {d['pages']} pages" if d["pages"] else ""
            _lineaje_payload = f"  {d['name']}: {d['chunks']} chunks{pages}  ({d['source']})"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:00e8b8470b515743aae25bedd8568e2e285bb0c381588e42e95cc06125061618'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:00e8b8470b515743aae25bedd8568e2e285bb0c381588e42e95cc06125061618', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 445, 'function': 'main'}, 'file': 'main.py', 'line': 445, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        return 0

    if not config.PERSIST_DIR.exists():
        _lineaje_payload = "No index found. Run: python main.py ingest"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9b1f43ccb2f166969145c4c093de6de4057d82204aa26b37952b4168d3b0bb40'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9b1f43ccb2f166969145c4c093de6de4057d82204aa26b37952b4168d3b0bb40', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 449, 'function': 'main'}, 'file': 'main.py', 'line': 449, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload, file=sys.stderr)
        return 1

    if args.cmd == "bench":
        from rag.eval.harness import run_experiments

        run_experiments(
            args.config,
            only=args.only.split(",") if args.only else None,
            verbose=args.verbose,
        )
        return 0

    if args.cmd == "eval":
        from rag.eval.runner import print_report, run_eval

        summary = run_eval(
            dataset=args.dataset,
            n=args.n,
            ks=tuple(int(k) for k in args.k.split(",")),
            temperature=args.temperature,
            top_k=args.top_k,
            limit=args.limit,
        )
        print_report(summary)
        return 0

    from rag.chain import build_guarded_chain

    chain = build_guarded_chain()

    if args.cmd == "ask":
        print_result(stream_answer(chain, args.question), answer_shown=True)
        return 0

    from rag.history import add_exchange, new_chat_id, redact_question

    from rag.prompt_cache import warm_in_background

    warm_in_background()  # prefill the judges' system prompts while you type
    chat_id, history = new_chat_id(), []
    _lineaje_payload = f"Type a question (or 'exit'). Chat id: {chat_id}"
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in main).
    #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:1ce4291f342868c1398ec34325ac1cfc8888425295e5efae74744a0b0603608a'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:1ce4291f342868c1398ec34325ac1cfc8888425295e5efae74744a0b0603608a', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'source': {'entity_type': 'agent', 'unique_org_id': 'vdna_7x1SqbGPY9RMRu8k', 'repository_uri': 'https://github.com/radhika-singh-10/luminusrag', 'file_path': 'main.py', 'line': 180, 'name': 'AgentEvents'}, 'invocation': {'file': 'main.py', 'line': 490, 'function': 'main'}, 'file': 'main.py', 'line': 490, 'function': 'main', 'agent_name': 'main', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    print(_lineaje_payload)
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q.lower() in {"exit", "quit", ""}:
            return 0
        result = stream_answer(chain, q, history)
        print_result(result, answer_shown=True)
        add_exchange(chat_id, redact_question(q), result["answer"])
        history += [{"role": "user", "content": redact_question(q)},
                    {"role": "assistant", "content": result["answer"]}]


if __name__ == "__main__":
    sys.exit(main())
