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
    return out
