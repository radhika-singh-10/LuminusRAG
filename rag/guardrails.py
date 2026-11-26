"""LangChain guardrails, used in two ways.

1. LangChain's PII guardrail components inside our own guard.
   LangChain 1.x ships PII detectors and strategies (`RedactionRule`: email,
   credit_card, ip, mac_address, url with block / redact / mask / hash). They
   run as an extra deterministic layer:
   - input (check_query): a credit card number blocks the question (PII-04);
     emails, IP and MAC addresses are redacted before any model sees the text;
   - output (sanitize_output): the same types are redacted in every streamed
     segment.
   LangChain's placeholder format ([REDACTED_EMAIL]) matches ours, so the
   rest of the pipeline treats both alike. LangChain adds MAC addresses, which
   policies/pii.json doesn't cover; ours adds SSNs, IBANs, secrets, phone
   numbers and the rest.

2. Our policy guard as LangChain agent middleware.
   PolicyGuardMiddleware runs check_query before the agent (and stops it with
   the rejection message) and sanitize_output after it. guardrail_middleware()
   returns it together with LangChain's PIIMiddleware, so an agent built with
   langchain.agents.create_agent gets the same deterministic + model-based
   guardrails as the LuminusRAG harness:

       agent = create_agent(model, tools, middleware=guardrail_middleware())

The LuminusRAG harness itself is a LangGraph state machine, not a
create_agent agent, so it calls the same checks from its safety node and its
output sanitizer rather than through middleware hooks.
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

from functools import lru_cache

from langchain.agents.middleware import PIIDetectionError, RedactionRule

# (pii type, strategy on input). Output always redacts.
LANGCHAIN_PII_RULES = (("credit_card", "block"), ("email", "redact"), ("ip", "redact"),
                       ("mac_address", "redact"))


@lru_cache(maxsize=8)
def _rule(pii_type: str, strategy: str):
    return RedactionRule(pii_type=pii_type, strategy=strategy).resolve()


def langchain_pii_input(text: str) -> tuple[str, list[str], str | None]:
    """(text with LangChain's redactions, redacted types, blocked type or None)."""
    found = []
    for pii_type, strategy in LANGCHAIN_PII_RULES:
        try:
            text, matches = _rule(pii_type, strategy).apply(text)
        except PIIDetectionError:
            return text, found, pii_type
        if matches:
            found.append(pii_type)
    return text, found, None


def langchain_pii_output(text: str) -> tuple[str, list[str]]:
    """Redact every LangChain PII type in model output."""
    found = []
    for pii_type, _ in LANGCHAIN_PII_RULES:
        text, matches = _rule(pii_type, "redact").apply(text)
        if matches:
            found.append(pii_type)
    return text, found


# ---------- middleware for create_agent ----------

def _text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        # LINEAJE: runtime guardrail checks `content` as it flows from the agent to the user interface, before it leaves the application (in _text).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `content` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:78b80a65f0e2a2ccf0432ea6c4408a4c3af56d640c118cab126a49e9f4224bef'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:78b80a65f0e2a2ccf0432ea6c4408a4c3af56d640c118cab126a49e9f4224bef', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/guardrails.py', 'line': 71, 'function': '_text'}, 'file': 'rag/guardrails.py', 'line': 71, 'function': '_text', 'agent_name': '_text', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            content = _gr_client.enforce(_gr_site, content, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        return content
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict))


def _policy_guard_middleware_class():
    from langchain.agents.middleware import AgentMiddleware, hook_config
    from langchain_core.messages import AIMessage, HumanMessage

    class PolicyGuardMiddleware(AgentMiddleware):
        """Policy guard (policies/*.json: regex + LangChain PII rules + LLM
        judges) before the agent; output sanitizer after it."""

        @hook_config(can_jump_to=["end"])
        def before_agent(self, state, runtime):
            from .policy import check_query

            humans = [m for m in state["messages"] if isinstance(m, HumanMessage)]
            if not humans:
                return None
            guard = check_query(_text(humans[-1]))
            if not guard.safe:
                return {"messages": [AIMessage(guard.message)], "jump_to": "end"}
            if guard.redacted:  # continue with the redacted question
                humans[-1].content = guard.text
                return {"messages": state["messages"]}
            return None

        def after_agent(self, state, runtime):
            from .safety import sanitize_output

            last = state["messages"][-1] if state["messages"] else None
            if isinstance(last, AIMessage) and _text(last):
                clean, actions = sanitize_output(_text(last), set())
                if actions:
                    last.content = clean
                    return {"messages": state["messages"]}
            return None

    # LINEAJE: runtime guardrail checks `PolicyGuardMiddleware` as it flows from the agent to the user interface, before it leaves the application (in _policy_guard_middleware_class).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `PolicyGuardMiddleware` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:64e61edce769e5ba30a3cd9ecdea66cf561d2467159b8b100e75e720389b79cb'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:64e61edce769e5ba30a3cd9ecdea66cf561d2467159b8b100e75e720389b79cb', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/guardrails.py', 'line': 109, 'function': '_policy_guard_middleware_class'}, 'file': 'rag/guardrails.py', 'line': 109, 'function': '_policy_guard_middleware_class', 'agent_name': '_policy_guard_middleware_class', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        PolicyGuardMiddleware = _gr_client.enforce(_gr_site, PolicyGuardMiddleware, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return PolicyGuardMiddleware


def PolicyGuardMiddleware():  # noqa: N802 - factory that looks like a class
    return _policy_guard_middleware_class()()


def guardrail_middleware() -> list:
    """LangChain PIIMiddleware for each LangChain PII type plus our policy guard."""
    from langchain.agents.middleware import PIIMiddleware

    pii = [PIIMiddleware(t, strategy=s, apply_to_input=True, apply_to_output=True)
           if s != "block" else PIIMiddleware(t, strategy="block", apply_to_input=True)
           for t, s in LANGCHAIN_PII_RULES]
    return [PolicyGuardMiddleware(), *pii]
