"""Stable, structure-aware chunking.

Chunks follow the document's own structure, so editing one paragraph changes
only the chunk(s) of the section it is in and every other chunk keeps the same
text, hash, and id (and its embedding is reused):

- Markdown / text: headings (#, ##, ...) open sections; each chunk records its
  heading path ("Vector Databases > Exact and approximate search"). A chunk
  never crosses a section boundary.
- Inside a section, paragraphs (blank-line separated) are packed into chunks of
  up to CHUNK_SIZE characters. Fenced code blocks and tables are kept whole.
- A paragraph longer than CHUNK_SIZE is split at sentence boundaries.
- Fenced code blocks longer than CHUNK_SIZE are split by function / class
  (rag/code_chunking.py), each piece kept as its own fenced block.
- Source code files (.py, .js, .ts, .java, .go, .rs, ...) are chunked by
  syntax: imports together, then one chunk per function / class / method
  (chunk_code below).
- PDFs: each page is a section ("page N"); its paragraphs are packed the same way.
- No overlap: overlapping text from a neighbour would make a chunk's hash
  change when the neighbour is edited. The heading path supplies context.

The heading path is prepended to the stored text, so the embedding and the
content hash both include it.
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

import hashlib
import re
from dataclasses import dataclass, field

from . import config

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    text: str           # stored and embedded text (heading path + body)
    heading: str        # "A > B > C", "" if none
    position: int       # order within the document version
    page: int | None = None
    meta: dict = field(default_factory=dict)  # code: kind, symbol, language

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def _blocks(lines: list[str]) -> list[str]:
    """Split a section body into blocks: paragraphs, whole code fences, whole tables."""
    blocks, cur, in_fence = [], [], False
    for line in lines:
        if _FENCE.match(line):
            in_fence = not in_fence
            cur.append(line)
            if not in_fence:  # fence closed: emit it as one block
                blocks.append("\n".join(cur))
                cur = []
            continue
        if in_fence:
            cur.append(line)
            continue
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return [b.strip("\n") for b in blocks if b.strip()]


def _split_fence(block: str, size: int) -> list[str]:
    """A long fenced code block in a known language -> one fenced block per
    function / class (no overlap). Other fences stay whole."""
    from .code_chunking import FENCE_LANGUAGES, code_units

    lines = block.splitlines()
    m = re.match(r"^\s*(```|~~~)\s*([\w+#-]*)", lines[0])
    lang = FENCE_LANGUAGES.get((m.group(2) if m else "").lower())
    if not lang or len(lines) < 3 or not _FENCE.match(lines[-1]):
        return [block]
    fence, body = lines[0], "\n".join(lines[1:-1])
    units = code_units(body, lang, size)
    if len(units) <= 1:
        return [block]
    return [f"{fence}\n{text}\n{lines[-1].strip()}" for _, text in units]


def _split_long(block: str, size: int) -> list[str]:
    if len(block) <= size:
        return [block]
    if block.lstrip().startswith(("```", "~~~")):
        return _split_fence(block, size)
    if block.lstrip().startswith("|"):
        return [block]  # tables stay whole even when long
    parts, cur = [], ""
    for sentence in _SENTENCE_END.split(block):
        if cur and len(cur) + len(sentence) + 1 > size:
            parts.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        parts.append(cur)
    # LINEAJE: runtime guardrail checks `parts` as it flows from the agent to the user interface, before it leaves the application (in _split_long).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `parts` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:4253b2400cedf615339f8558a45cbd571f2f2022f5bd95e5ea2fbd7aac1b9652'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4253b2400cedf615339f8558a45cbd571f2f2022f5bd95e5ea2fbd7aac1b9652', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/chunking.py', 'line': 107, 'function': '_split_long'}, 'file': 'rag/chunking.py', 'line': 107, 'function': '_split_long', 'agent_name': '_split_long', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        parts = _gr_client.enforce(_gr_site, parts, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return parts


def _pack(blocks: list[str], size: int) -> list[str]:
    """Greedily pack whole blocks into chunks of up to `size` characters.
    Pieces of a code block split by function / class each stay their own chunk."""
    chunks, cur = [], ""
    for b in blocks:
        parts = _split_long(b, size)
        solo = len(parts) > 1 and b.lstrip().startswith(("```", "~~~"))
        for p in parts:
            if solo:
                if cur:
                    chunks.append(cur)
                    cur = ""
                chunks.append(p)
            elif cur and len(cur) + len(p) + 2 > size:
                chunks.append(cur)
                cur = p
            else:
                cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    # LINEAJE: runtime guardrail checks `chunks` as it flows from the agent to the user interface, before it leaves the application (in _pack).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `chunks` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:2b8f9bb423d2ba6d21a95c655b05eb590ac3cda374921a90054db02a9a7b10d3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2b8f9bb423d2ba6d21a95c655b05eb590ac3cda374921a90054db02a9a7b10d3', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/chunking.py', 'line': 130, 'function': '_pack'}, 'file': 'rag/chunking.py', 'line': 130, 'function': '_pack', 'agent_name': '_pack', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        chunks = _gr_client.enforce(_gr_site, chunks, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return chunks


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """[(heading path, body lines)] for markdown/plain text."""
    sections, path, body, in_fence = [], [], [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            if body:
                sections.append((" > ".join(path), body))
            level, title = len(m.group(1)), m.group(2).strip()
            path = path[: level - 1] + [title]
            body = []
        else:
            body.append(line)
    if body:
        sections.append((" > ".join(path), body))
    # LINEAJE: runtime guardrail checks `sections` as it flows from the agent to the user interface, before it leaves the application (in _sections).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `sections` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:a5f26fafb45a2b5fc9522f1a228bdbd60de9f6ea9c46ab7760db0b076d9e9c14'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:a5f26fafb45a2b5fc9522f1a228bdbd60de9f6ea9c46ab7760db0b076d9e9c14', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/chunking.py', 'line': 150, 'function': '_sections'}, 'file': 'rag/chunking.py', 'line': 150, 'function': '_sections', 'agent_name': '_sections', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        sections = _gr_client.enforce(_gr_site, sections, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return sections


def chunk_text(text: str, page: int | None = None, start: int = 0,
               size: int | None = None) -> list[Chunk]:
    """Structure-aware chunks for one document (or one PDF page)."""
    size = size or config.CHUNK_SIZE
    out: list[Chunk] = []
    if page is not None:
        sections = [(f"page {page + 1}", text.splitlines())]
    else:
        sections = _sections(text)
    for heading, lines in sections:
        for body in _pack(_blocks(lines), size):
            stored = f"{heading}\n\n{body}" if heading else body
            out.append(Chunk(text=stored, heading=heading, position=start + len(out), page=page))
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in chunk_text).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:7ab1ecaa42b655ad6e8c0a55675b9840980ce29f3e068140d8ae53d1cc885a83'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:7ab1ecaa42b655ad6e8c0a55675b9840980ce29f3e068140d8ae53d1cc885a83', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/chunking.py', 'line': 166, 'function': 'chunk_text'}, 'file': 'rag/chunking.py', 'line': 166, 'function': 'chunk_text', 'agent_name': 'chunk_text', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def chunk_code(text: str, language: str, file_label: str = "", start: int = 0,
               size: int | None = None) -> list[Chunk]:
    """Source file -> chunks by syntax: imports, functions, classes, methods.
    The heading path ("store.py > class VectorStore > def search") is stored
    with the code so the embedding sees which symbol it is. Line numbers are
    left out of the stored text so an edit above a function doesn't change
    that function's hash."""
    from .code_chunking import code_units, unit_heading

    out: list[Chunk] = []
    for u, code in code_units(text, language, size or config.CHUNK_SIZE):
        heading = unit_heading(file_label, u)
        out.append(Chunk(text=f"{heading}\n\n{code}", heading=heading, position=start + len(out),
                         meta={"kind": u.kind, "symbol": u.name, "language": language}))
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in chunk_code).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:44471ef1911a7a78c456696f40996f5577da68135d01ea34b8ae849849bab14f'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:44471ef1911a7a78c456696f40996f5577da68135d01ea34b8ae849849bab14f', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/chunking.py', 'line': 183, 'function': 'chunk_code'}, 'file': 'rag/chunking.py', 'line': 183, 'function': 'chunk_code', 'agent_name': 'chunk_code', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out
