"""Safety checks for questions and web content.

- redact_pii: strips personal data and secrets before anything leaves the
  machine (web search) or is stored from the web.
- find_command: flags questions that contain shell/code commands. The system
  never executes anything, and such questions are refused outright.
- looks_like_injection: flags web passages that try to instruct the model;
  those passages are dropped before they reach the model or the store.

These are pattern checks. The Ollama intent gate adds a language-independent
check that refuses requests to perform actions (see rag/intent.py).
"""
import re

# ---------- PII and secrets ----------

_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("secret", re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}"
        r"|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
        r"|xox[abp]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})\b")),
    ("secret", re.compile(
        r"(?i)\b(?:password|passwd|pwd|api[_-]?key|token|secret|bearer)\b\s*[:=]?\s*\S{6,}")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b")),
    ("ip", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
    ("phone", re.compile(
        r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{3,4}[\s.-]\d{3,4}(?![\w-])")),
    ("aadhaar", re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]


def _luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits][::-1]
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n * 2 > 9 else n * 2) for i, n in enumerate(nums))
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Return (text with PII replaced by [REDACTED_<KIND>], kinds found)."""
    found: list[str] = []

    for kind, pattern in _PII_PATTERNS:
        def sub(m: re.Match, kind=kind) -> str:
            if kind == "card":
                digits = re.sub(r"\D", "", m.group())
                if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                    return m.group()
            found.append(kind)
            return f"[REDACTED_{kind.upper()}]"

        text = pattern.sub(sub, text)
    return text, sorted(set(found))


_PLACEHOLDER = re.compile(r"\[REDACTED_[A-Z]+\]")


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


# ---------- prompt injection in web content ----------

_INJECTION_PATTERNS = [
    # English
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier|preceding) (?:instructions|prompts|rules|messages)",
    r"disregard (?:all |any )?(?:the )?(?:previous|prior|above|system) (?:instructions|prompt|rules)",
    r"forget (?:all |everything |your )?(?:previous |prior )?(?:instructions|rules)",
    r"\b(?:reveal|print|show|output|repeat|leak|display)\b.{0,40}\b(?:system|developer|hidden) (?:prompt|instructions)\b",
    r"\byou are now\b|\bact as (?:an?|the) \w+|\bfrom now on,? you\b",
    r"\bnew instructions?\s*:",
    r"\b(?:execute|run) (?:the following|this) (?:command|code|script)",
    r"\b(?:assistant|ai|model|llm|chatbot)s?,? (?:must|should) (?:now )?(?:ignore|reveal|send|execute|output)",
    r"<\s*/?\s*(?:system|instructions?)\s*>|\[\s*(?:system|INST)\s*\]",
    # Other languages
    r"ignora (?:todas )?las instrucciones",                      # es
    r"ignorez (?:toutes )?les instructions",                     # fr
    r"ignoriere (?:alle )?(?:vorherigen )?anweisungen",          # de
    r"ignora (?:tutte )?le istruzioni",                          # it
    r"ignore (?:todas )?as instruções",                          # pt
    r"игнорируй(?:те)? (?:все )?(?:предыдущие )?инструкции",     # ru
    r"忽略(?:之前|以上|所有)?的?(?:指令|指示|说明)",                 # zh
    r"(?:以前|前)の指示を無視",                                     # ja
    r"이전 지시(?:를|사항을)? 무시",                                 # ko
    r"निर्देशों को (?:अनदेखा|नज़रअंदाज़|नजरअंदाज)",                    # hi
    r"تجاهل (?:جميع )?التعليمات",                                 # ar
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))
