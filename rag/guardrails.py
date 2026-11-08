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
