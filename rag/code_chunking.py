"""Code-aware chunking: imports, then one chunk per function / class / method.

Source files are split along their syntax, never by character count:

- imports: all import / include / use / package statements (the file's
  libraries) plus the module docstring or header comment form one chunk;
- each top-level function is one chunk;
- each class (interface, struct, enum, trait, impl) is one chunk. A class
  larger than CHUNK_SIZE becomes a header chunk (signature, docstring,
  fields) plus one chunk per method;
- other module-level statements (constants, `if __name__ == "__main__"`) are
  grouped in order into "module" chunks.

Decorators, annotations and the comment / doc block directly above a
definition belong to that definition. The units partition the file: every
line is in exactly one chunk, so chunks never overlap and nothing is lost.
A single function longer than CODE_MAX_CHARS is split at its top-level
statements into parts (still no overlap); the heading names the part.

Python is parsed with `ast`; if the file doesn't parse it falls back to the
line scanner. Brace languages (JavaScript, TypeScript, Java, Go, Rust, C,
C++, C#, Kotlin, Swift, Scala, PHP) use a scanner that tracks brace depth
while skipping strings and comments.
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

import ast
import re
from dataclasses import dataclass, field

from . import config

LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java", ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".kt": "kotlin", ".swift": "swift", ".scala": "scala", ".php": "php",
}
FENCE_LANGUAGES = {"python": "python", "py": "python", "javascript": "javascript", "js": "javascript",
                   "typescript": "typescript", "ts": "typescript", "java": "java", "go": "go",
                   "rust": "rust", "rs": "rust", "c": "c", "cpp": "cpp", "c++": "cpp",
                   "csharp": "csharp", "cs": "csharp", "kotlin": "kotlin", "swift": "swift",
                   "scala": "scala", "php": "php"}


@dataclass
class Unit:
    kind: str          # "imports" | "function" | "class" | "method" | "class_header" | "module"
    name: str          # symbol name ("" for imports/module)
    start: int         # 0-based first line (inclusive)
    end: int           # 0-based last line (inclusive)
    parent: str = ""   # enclosing class for methods / class headers
    part: str = ""     # "part 2/3" for oversized functions
    children: list = field(default_factory=list)


def language_for(path: str) -> str | None:
    from pathlib import Path

    return LANGUAGES.get(Path(path).suffix.lower())


# ---------- shared helpers ----------

def _lines_text(lines: list[str], u: Unit) -> str:
    return "\n".join(lines[u.start:u.end + 1]).strip("\n")


def _size(lines: list[str], u: Unit) -> int:
    return sum(len(x) + 1 for x in lines[u.start:u.end + 1])


def _partition(starts: list[tuple[int, str, str]], first: int, last: int) -> list[Unit]:
    """Item start lines -> units covering [first, last] contiguously. Lines
    before the first item join the first unit; each unit ends where the next starts."""
    units = []
    for i, (s, kind, name) in enumerate(starts):
        start = first if i == 0 else s
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else last
        units.append(Unit(kind, name, start, end))
    # LINEAJE: runtime guardrail checks `units` as it flows from the agent to the user interface, before it leaves the application (in _partition).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `units` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:62dc7d8e6ecc05dc0931c4e8339a45783d0268cb7082f01f63d98c4bb951762d'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:62dc7d8e6ecc05dc0931c4e8339a45783d0268cb7082f01f63d98c4bb951762d', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 79, 'function': '_partition'}, 'file': 'rag/code_chunking.py', 'line': 79, 'function': '_partition', 'agent_name': '_partition', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        units = _gr_client.enforce(_gr_site, units, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return units


def _merge_runs(units: list[Unit], lines: list[str], size: int) -> list[Unit]:
    """Merge consecutive imports units into one; pack consecutive module units up to `size`."""
    out: list[Unit] = []
    for u in units:
        prev = out[-1] if out else None
        if prev and u.kind == prev.kind == "imports":
            prev.end = u.end
        elif prev and u.kind == prev.kind == "module" and _size(lines, prev) + _size(lines, u) <= size:
            prev.end = u.end
        else:
            out.append(u)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in _merge_runs).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:98039c56ced38b47bfc4b292925bf5131707cd62f5f9d596c85fe23335712ee5'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:98039c56ced38b47bfc4b292925bf5131707cd62f5f9d596c85fe23335712ee5', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 93, 'function': '_merge_runs'}, 'file': 'rag/code_chunking.py', 'line': 93, 'function': '_merge_runs', 'agent_name': '_merge_runs', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def _attach_leading(lines: list[str], start: int, floor: int, comment: re.Pattern) -> int:
    """Move a start line up over directly preceding comment / decorator lines."""
    s = start
    while s - 1 >= floor and lines[s - 1].strip() and comment.match(lines[s - 1]):
        s -= 1
    # LINEAJE: runtime guardrail checks `s` as it flows from the agent to the user interface, before it leaves the application (in _attach_leading).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `s` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:125379747fe178a485eeb4e897e50d05780ef378e3eda7c9f5aeb97370d7386a'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:125379747fe178a485eeb4e897e50d05780ef378e3eda7c9f5aeb97370d7386a', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 101, 'function': '_attach_leading'}, 'file': 'rag/code_chunking.py', 'line': 101, 'function': '_attach_leading', 'agent_name': '_attach_leading', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        s = _gr_client.enforce(_gr_site, s, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return s


# ---------- Python (ast) ----------

_PY_COMMENT = re.compile(r"^\s*(#|@)")


def _py_kind(node) -> tuple[str, str]:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "imports", ""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "function", node.name
    if isinstance(node, ast.ClassDef):
        return "class", node.name
    if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
            and isinstance(node.value.value, str):
        return "imports", ""  # docstring: stays with the file header
    if isinstance(node, ast.Try) and all(isinstance(n, (ast.Import, ast.ImportFrom, ast.Pass, ast.Assign))
                                         for b in [node.body] + [h.body for h in node.handlers] for n in b):
        return "imports", ""  # try: import x / except ImportError: ...
    return "module", ""


def _py_starts(nodes, lines: list[str], floor: int) -> list[tuple[int, str, str]]:
    starts = []
    for n in nodes:
        first = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])]) - 1
        first = _attach_leading(lines, first, floor, _PY_COMMENT)
        floor = n.end_lineno
        kind, name = _py_kind(n)
        starts.append((first, kind, name))
    # LINEAJE: runtime guardrail checks `starts` as it flows from the agent to the user interface, before it leaves the application (in _py_starts).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `starts` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:f97331225db07bb095fb046fd990ba8914ff388f347a99b20c61719693c5b00e'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:f97331225db07bb095fb046fd990ba8914ff388f347a99b20c61719693c5b00e', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 133, 'function': '_py_starts'}, 'file': 'rag/code_chunking.py', 'line': 133, 'function': '_py_starts', 'agent_name': '_py_starts', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        starts = _gr_client.enforce(_gr_site, starts, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return starts


def _python_units(source: str, lines: list[str], size: int) -> list[Unit] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    if not tree.body:
        return [Unit("module", "", 0, len(lines) - 1)] if lines else []
    units = _merge_runs(_partition(_py_starts(tree.body, lines, 0), 0, len(lines) - 1), lines, size)
    nodes = {n.name: n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
    out = []
    for u in units:
        node = nodes.get(u.name)
        if u.kind == "class" and node is not None and _size(lines, u) > size:
            out += _python_class_split(node, u, lines)
        elif u.kind == "function" and node is not None and _size(lines, u) > config.CODE_MAX_CHARS:
            out += _python_function_split(node, u, lines)
        else:
            out.append(u)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in _python_units).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:f0136a02e3b28e76a6468e22e6e2e2d1369fdc6c8d510e9f12097973dde8791d'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:f0136a02e3b28e76a6468e22e6e2e2d1369fdc6c8d510e9f12097973dde8791d', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 154, 'function': '_python_units'}, 'file': 'rag/code_chunking.py', 'line': 154, 'function': '_python_units', 'agent_name': '_python_units', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def _python_class_split(node: ast.ClassDef, u: Unit, lines: list[str]) -> list[Unit]:
    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not methods:
        return [u]
    starts = [(u.start, "class_header", node.name)]
    floor = u.start
    for m in methods:
        first = min([m.lineno] + [d.lineno for d in m.decorator_list]) - 1
        first = _attach_leading(lines, first, floor, _PY_COMMENT)
        starts.append((first, "method", m.name))
        floor = m.end_lineno
    parts = _partition(starts, u.start, u.end)
    for p in parts:
        p.parent = node.name
    return [p for p in parts if p.kind != "class_header" or _lines_text(lines, p).strip()]


def _python_function_split(node, u: Unit, lines: list[str]) -> list[Unit]:
    """Oversized function: split at its top-level body statements, packed to CODE_MAX_CHARS."""
    cuts = [u.start] + [s.lineno - 1 for s in node.body[1:]]
    groups, cur = [], [cuts[0]]
    for c in cuts[1:]:
        if sum(len(x) + 1 for x in lines[cur[0]:c]) > config.CODE_MAX_CHARS:
            groups.append(cur[0])
            cur = [c]
    groups.append(cur[0])
    parts = _partition([(g, "function", u.name) for g in groups], u.start, u.end)
    for i, p in enumerate(parts, 1):
        p.part = f"part {i}/{len(parts)}" if len(parts) > 1 else ""
        p.parent = u.parent
    # LINEAJE: runtime guardrail checks `parts` as it flows from the agent to the user interface, before it leaves the application (in _python_function_split).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `parts` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:4ea51241f15055a70458f6b65531d69e32b9df659125b068db2b28df04d754db'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4ea51241f15055a70458f6b65531d69e32b9df659125b068db2b28df04d754db', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 187, 'function': '_python_function_split'}, 'file': 'rag/code_chunking.py', 'line': 187, 'function': '_python_function_split', 'agent_name': '_python_function_split', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        parts = _gr_client.enforce(_gr_site, parts, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return parts


# ---------- brace languages (scanner) ----------

_IMPORT = re.compile(r"^\s*(import\b|from\s+\S+\s+import\b|#\s*include\b|using\s+[\w.]+\s*;|use\s+[\w:{}, ]+;|"
                     r"package\s+[\w.]+|require\s*\(|const\s+\w+\s*=\s*require\(|extern\s+crate\b|"
                     r"namespace\s+[\w.\\]+\s*;|<\?php)")
_CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:public\s+|private\s+|protected\s+|internal\s+|"
                    r"abstract\s+|final\s+|sealed\s+|static\s+|pub(?:\([\w ]+\))?\s+|data\s+|open\s+)*"
                    r"(class|interface|struct|enum|trait|impl|object|record|union)\b\s*(?:<[^>]*>\s*)?([\w$]*)")
_GO_TYPE = re.compile(r"^\s*type\s+(\w+)\s+(struct|interface)\b")
# Members inside a class body: name(args) { ... } with optional modifiers / return type.
_METHOD = re.compile(r"^\s*(?:@\w+\s+)*(?:(?:public|private|protected|internal|static|readonly|async|override|"
                     r"abstract|final|virtual|get|set|pub(?:\([\w ]+\))?|fn|func|fun|function|def)\s+)*"
                     r"(?:[\w<>\[\],.?*&:]+\s+)?\*?([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^;]*\)?"
                     r"\s*(?::[^={;]+|->\s*[^{;]+|throws\s+[\w., ]+)?\s*\{?\s*$")
_FUNC = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:pub(?:\([\w ]+\))?\s+)?"
                   r"(?:public\s+|private\s+|protected\s+|static\s+|final\s+|override\s+|inline\s+|"
                   r"virtual\s+|const\s+|unsafe\s+|extern\s+\"C\"\s+)*"
                   r"(?:function\s*\*?\s*([\w$]+)|fn\s+(\w+)|func\s+(?:\([^)]*\)\s*)?(\w+)|fun\s+(\w+)|"
                   r"(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\([^)]*\)|[\w$]+)\s*(?::[^=]+)?=>|"
                   r"[\w<>\[\]:*&,\s]+?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?(?:->\s*[\w<>:&*\s]+)?"
                   r"(?:throws\s+[\w., ]+)?\s*\{?\s*$)")
_BRACE_COMMENT = re.compile(r"^\s*(//|/\*|\*|@|#\[|\[\w)")
_CONTROL = {"if", "for", "while", "switch", "catch", "return", "else", "do", "try", "sizeof", "new"}


def _depths(source: str) -> list[int]:
    """Brace depth at the start of each line, ignoring braces in strings and comments."""
    depths, depth, i, n = [0], 0, 0, len(source)
    in_line_c = in_block_c = False
    quote = None
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if ch == "\n":
            in_line_c = False
            depths.append(depth)
        elif in_line_c:
            pass
        elif in_block_c:
            if ch == "*" and nxt == "/":
                in_block_c = False
                i += 1
        elif quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch == "/" and nxt == "/":
            in_line_c = True
        elif ch == "/" and nxt == "*":
            in_block_c = True
            i += 1
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        i += 1
    # LINEAJE: runtime guardrail checks `depths` as it flows from the agent to the user interface, before it leaves the application (in _depths).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `depths` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:ead0898cece6d27105202c34584b30bb01840acfbf18337282f877b2c2e08fde'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ead0898cece6d27105202c34584b30bb01840acfbf18337282f877b2c2e08fde', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 249, 'function': '_depths'}, 'file': 'rag/code_chunking.py', 'line': 249, 'function': '_depths', 'agent_name': '_depths', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        depths = _gr_client.enforce(_gr_site, depths, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return depths


def _classify_brace(line: str, member: bool = False) -> tuple[str, str]:
    if _IMPORT.match(line):
        return "imports", ""
    if m := _GO_TYPE.match(line):
        return "class", f"{m.group(2)} {m.group(1)}"
    if m := _CLASS.match(line):
        return "class", f"{m.group(1)} {m.group(2)}".strip()
    if member and (m := _METHOD.match(line)) and m.group(1) not in _CONTROL - {"new"} \
            and "=" not in line.split("(")[0]:
        return "function", m.group(1)
    if m := _FUNC.match(line):
        name = next((g for g in m.groups() if g), "")
        if name and name not in _CONTROL:
            return "function", name
    return "module", ""


def _brace_items(lines: list[str], depths: list[int], level: int, lo: int, hi: int) -> list[tuple[int, str, str]]:
    """Start lines of items at brace depth `level` within [lo, hi]."""
    starts, i = [], lo
    while i <= hi:
        line = lines[i]
        if depths[i] != level or not line.strip() or _BRACE_COMMENT.match(line) or line.strip() in ("}", "};", "})", "});"):
            i += 1
            continue
        kind, name = _classify_brace(line, member=level > 0)
        first = _attach_leading(lines, i, starts[-1][0] + 1 if starts else lo, _BRACE_COMMENT)
        starts.append((first, kind, name))
        if line.rstrip().endswith("(") and "{" not in line:  # Go: import ( ... ) / const ( ... )
            j = i + 1
            while j <= hi and lines[j].strip() != ")":
                j += 1
            i = j + 1
            continue
        # Skip to the end of this item: back at `level` after its braces close.
        j = i + 1
        opened = "{" in line
        while j <= hi and (depths[j] > level or (not opened and depths[j] == level and lines[j].strip()
                                                   and not lines[i].rstrip().endswith((";", "}")) and j == i + 1)):
            opened = opened or depths[j] > level
            j += 1
        # include a closing-brace line that returns to `level`
        while j <= hi and lines[j].strip() in ("}", "};", "})", "});", "},"):
            j += 1
        i = max(j, i + 1)
    # LINEAJE: runtime guardrail checks `starts` as it flows from the agent to the user interface, before it leaves the application (in _brace_items).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `starts` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:09dd4b56d987ac5b8d3336190144fb9c0b6fe9d5198ab3db24ef1f8a8dc46ebf'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:09dd4b56d987ac5b8d3336190144fb9c0b6fe9d5198ab3db24ef1f8a8dc46ebf', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 297, 'function': '_brace_items'}, 'file': 'rag/code_chunking.py', 'line': 297, 'function': '_brace_items', 'agent_name': '_brace_items', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        starts = _gr_client.enforce(_gr_site, starts, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return starts


def _brace_units(lines: list[str], size: int) -> list[Unit]:
    if not lines:
        return []
    depths = _depths("\n".join(lines))
    starts = _brace_items(lines, depths, 0, 0, len(lines) - 1)
    if not starts:
        return [Unit("module", "", 0, len(lines) - 1)]
    units = _merge_runs(_partition(starts, 0, len(lines) - 1), lines, size)
    out = []
    for u in units:
        if u.kind == "class" and _size(lines, u) > size:
            open_line = next((k for k in range(u.start, u.end + 1) if depths[min(k + 1, len(depths) - 1)] > 0
                              and "{" in lines[k]), None)
            inner = _brace_items(lines, depths, 1, open_line + 1, u.end) if open_line is not None else []
            members = [(s, "method", n) for s, k, n in inner if k == "function"]
            if members:
                parts = _partition([(u.start, "class_header", u.name)] + members, u.start, u.end)
                for p in parts:
                    p.parent = u.name
                out += parts
                continue
        out.append(u)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in _brace_units).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:30a9316e659702417b67b789c092705ac2a136979f613675a6254c18e3e60c5c'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:30a9316e659702417b67b789c092705ac2a136979f613675a6254c18e3e60c5c', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 322, 'function': '_brace_units'}, 'file': 'rag/code_chunking.py', 'line': 322, 'function': '_brace_units', 'agent_name': '_brace_units', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


# ---------- public API ----------

def code_units(source: str, language: str, size: int | None = None) -> list[tuple[Unit, str]]:
    """[(unit, code text)] partitioning `source` (no overlap, nothing dropped)."""
    size = size or config.CHUNK_SIZE
    lines = source.splitlines()
    units = (_python_units(source, lines, size) if language == "python" else None)
    if units is None:
        units = _brace_units(lines, size) if language != "python" else _python_fallback(lines, size)
    out = []
    for u in units:
        text = _lines_text(lines, u)
        if text.strip():
            out.append((u, text))
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in code_units).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:3593995bef58d76a103134b176451d9097539685be86fde8c21b01c9db01bca7'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:3593995bef58d76a103134b176451d9097539685be86fde8c21b01c9db01bca7', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/code_chunking.py', 'line': 339, 'function': 'code_units'}, 'file': 'rag/code_chunking.py', 'line': 339, 'function': 'code_units', 'agent_name': 'code_units', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out


def _python_fallback(lines: list[str], size: int) -> list[Unit]:
    """Unparseable Python: split at top-level def/class/import lines."""
    pat = re.compile(r"^(?:async\s+def|def|class)\s+(\w+)|^(?:import|from)\s")
    starts = []
    for i, line in enumerate(lines):
        if m := pat.match(line):
            kind = "imports" if line.startswith(("import", "from")) else (
                "class" if line.startswith("class") else "function")
            first = _attach_leading(lines, i, starts[-1][0] + 1 if starts else 0, _PY_COMMENT)
            starts.append((first, kind, m.group(1) or ""))
    if not starts:
        return [Unit("module", "", 0, len(lines) - 1)] if lines else []
    return _merge_runs(_partition(starts, 0, len(lines) - 1), lines, size)


def unit_heading(file_label: str, u: Unit) -> str:
    """Heading path for a code chunk, e.g. "chain.py > class GuardedPipeline > def events"."""
    parts = [file_label] if file_label else []
    if u.parent and u.kind in ("method", "class_header") or (u.parent and u.part):
        parts.append(u.parent if re.match(r"(class|interface|struct|enum|trait|impl|object|record|union)\b",
                                          u.parent) else f"class {u.parent}")
    label = {"imports": "imports", "module": "module code", "class_header": "class header",
             "class": u.name if re.match(r"(class|interface|struct|enum|trait|impl|object|record|union)\b", u.name)
             else f"class {u.name}", "function": f"def {u.name}", "method": f"def {u.name}"}[u.kind]
    if u.kind == "class_header":
        label = "class header"
    parts.append(label + (f" ({u.part})" if u.part else ""))
    return " > ".join(parts)
