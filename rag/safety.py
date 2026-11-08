"""Deterministic safety checks, driven by the JSON policies in policies/.

- redact_pii: replaces personal data and secrets using the detectors in
  policies/pii.json.
- injection_rule: the first prompt-injection rule (policies/prompt_injection.json)
  whose regex matches, or None.
- find_command: flags shell/code commands. The system never executes anything.
- strip_hidden_content: removes HTML comments and images that readers don't
  see but a model would.
- sanitize_output: cleans a model answer before it is shown or saved.

The LLM-based policy checks build on these in rag/policy.py.
"""
import base64
import binascii
import json
import re
from functools import lru_cache
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"


@lru_cache(maxsize=None)
def load_policy(name: str) -> dict:
    """Load policies/<name>.json and compile its regexes."""
    data = json.loads((POLICY_DIR / f"{name}.json").read_text(encoding="utf-8"))
    for rule in data["rules"]:
        rule["_compiled"] = [re.compile(p, re.IGNORECASE) for p in rule.get("patterns", [])]
    for det in data.get("detectors", []):
        det["_compiled"] = re.compile(det["pattern"])
    return data


# ---------- PII and secrets ----------

def _luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits][::-1]
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n * 2 > 9 else n * 2) for i, n in enumerate(nums))
    return total % 10 == 0


_PLACEHOLDER_SECRET = re.compile(
    r"your[-_ ]?(?:key|token|secret|password)|<[^>]*>|x{3,}|\.\.\.|placeholder|changeme|\*{3,}",
    re.IGNORECASE)


def _valid(det: dict, value: str) -> bool:
    if det["kind"] == "secret" and _PLACEHOLDER_SECRET.search(value):
        return False  # documentation placeholder, not a real secret
    if det.get("validator") == "luhn":
        digits = re.sub(r"\D", "", value)
        return 13 <= len(digits) <= 19 and _luhn_ok(digits)
    return True


def detect_pii(text: str) -> list[tuple[str, str]]:
    """[(kind, matched text)] for every PII detector hit, in policy order."""
    return [
        (det["kind"], m.group())
        for det in load_policy("pii")["detectors"]
        for m in det["_compiled"].finditer(text)
        if _valid(det, m.group())
    ]


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Return (text with PII replaced by [REDACTED_<KIND>], kinds found)."""
    found: list[str] = []
    for det in load_policy("pii")["detectors"]:
        def sub(m: re.Match, det=det) -> str:
            if not _valid(det, m.group()):
                return m.group()
            found.append(det["kind"])
            value = m.group()
            return f"[REDACTED_{det['kind'].upper()}]" + value[len(value.rstrip()):]  # keep trailing space

        text = det["_compiled"].sub(sub, text)
    return text, sorted(set(found))


_PLACEHOLDER = re.compile(r"\[REDACTED_[A-Z_]+\]")


def strip_redactions(text: str) -> str:
    """Drop the parts of a question that carried personal data.

    Sentences containing a [REDACTED_*] placeholder are removed ("My email is
    [REDACTED_EMAIL]. How does RLHF work?" -> "How does RLHF work?"), so words
    like "email" or "phone" don't steer search. If every sentence had PII, only
    the placeholders themselves are removed.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    clean = [s for s in sentences if not _PLACEHOLDER.search(s)]
    text = " ".join(clean) if clean else _PLACEHOLDER.sub(" ", text)
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    return " ".join(text.split())


# ---------- prompt injection ----------

_B64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def decoded_payloads(text: str) -> list[str]:
    """Readable text hidden in base64 blobs inside `text`."""
    out = []
    for blob in _B64.findall(text):
        try:
            decoded = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded and sum(c.isprintable() for c in decoded) / len(decoded) > 0.9:
            out.append(decoded)
    return out


def injection_rule(text: str, mode: str = "query") -> dict | None:
    """First prompt-injection rule (that applies to `mode`) whose pattern matches
    text or readable base64 inside it. mode is "query" or "document"."""
    candidates = [text, *decoded_payloads(text)]
    for rule in load_policy("prompt_injection")["rules"]:
        if mode not in rule.get("applies_to", ["query", "document"]):
            continue
        for pattern in rule["_compiled"]:
            for candidate in candidates:
                if m := pattern.search(candidate):
                    return {"id": rule["id"], "name": rule["name"], "match": m.group()[:80],
                            "encoded": candidate is not text}
    return None


def looks_like_injection(text: str, mode: str = "document") -> bool:
    return injection_rule(text, mode) is not None


# ---------- hidden content ----------

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def strip_hidden_content(text: str) -> tuple[str, dict]:
    """Remove HTML comments and images (tracking pixels, exfiltration URLs)."""
    counts = {
        "html_comments": len(_HTML_COMMENT.findall(text)),
        "images": len(_MD_IMAGE.findall(text)) + len(_HTML_IMG.findall(text)),
    }
    text = _HTML_COMMENT.sub(" ", text)
    text = _MD_IMAGE.sub(" ", text)
    text = _HTML_IMG.sub(" ", text)
    return text, counts


_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)[^)]*\)")
_BARE_URL = re.compile(r"(?<!\()https?://[^\s)>\]]+")


def _host(url: str) -> str:
    return re.sub(r"^https?://([^/:]+).*", r"\1", url).lower()


def sanitize_output(answer: str, allowed_urls: set[str]) -> tuple[str, list[str]]:
    """Clean a model answer before it is shown or saved.

    Removes images, unwraps links to hosts that weren't among the retrieved
    sources, removes unknown bare URLs, and redacts PII and secrets.
    Returns (answer, actions taken).
    """
    actions = []
    answer, hidden = strip_hidden_content(answer)
    if hidden["images"] or hidden["html_comments"]:
        actions.append("removed images/hidden content")
    allowed = {_host(u) for u in allowed_urls}

    def link(m: re.Match) -> str:
        if _host(m.group(2)) in allowed:
            return m.group(0)
        actions.append("removed unknown link")
        return m.group(1)

    def bare(m: re.Match) -> str:
        if _host(m.group(0)) in allowed:
            return m.group(0)
        actions.append("removed unknown link")
        return "[link removed]"

    answer = _MD_LINK.sub(link, answer)
    answer = _BARE_URL.sub(bare, answer)
    answer, kinds = redact_pii(answer)
    if kinds:
        actions.append("redacted " + ", ".join(kinds))
    from . import config

    if config.LANGCHAIN_PII:  # LangChain's PII guardrail rules (rag/guardrails.py)
        from .guardrails import langchain_pii_output

        answer, lc_found = langchain_pii_output(answer)
        if lc_found:
            actions.append("redacted " + ", ".join(lc_found) + " (LangChain PII)")
    return answer, sorted(set(actions))


# ---------- commands / code execution requests ----------

_COMMAND_PATTERNS = [
    r"^\s*(?:\$|PS [A-Z]:\\>)\s*\w+",                               # shell prompts
    r"\b(?:sudo|rm\s+-rf?|chmod|chown|mkfs|dd\s+if=|kill\s+-9|shutdown|reboot)\b",
    r"\b(?:curl|wget|nc|ncat|netcat|ssh|scp|ftp|telnet)\s+(?:-\S+\s+)*\S+",
    r"\b(?:bash|sh|zsh|powershell|pwsh|cmd(?:\.exe)?)\s+(?:-c|/c|-Command|-enc)\b",
    r"\b(?:python3?|node|ruby|perl|php)\s+-[ce]\b",
    r"\b(?:os\.system|subprocess\.|exec\s*\(|eval\s*\(|__import__|Runtime\.getRuntime)",
    r"\b(?:Invoke-WebRequest|Invoke-Expression|iex|Start-Process)\b",
    r"\b(?:DROP|TRUNCATE)\s+TABLE\b|\bDELETE\s+FROM\b|\bINSERT\s+INTO\b|;\s*--",
    r"(?:\|\s*(?:sh|bash)\b|`[^`]*\b(?:rm|curl|wget|cat|ls)\b[^`]*`|\$\([^)]*\))",
    r"(?:/etc/passwd|/etc/shadow|~/\.ssh|id_rsa|C:\\Windows\\System32)",
]
_COMMAND_RE = re.compile(
    "|".join(f"(?:{p})" for p in _COMMAND_PATTERNS), re.IGNORECASE | re.MULTILINE
)


def find_command(text: str) -> str | None:
    """The first command-like fragment in text, or None."""
    m = _COMMAND_RE.search(text)
    return m.group().strip() if m else None
