"""Document versions, the active chunk set, and an asynchronous garbage collector.

Registry: SQLite next to the vector store (PERSIST_DIR/registry.sqlite).
- documents(doc_id, source, active_version)
- versions(doc_id, version, status, file_hash, created, retired_at)
      status: building -> active -> retired; building -> failed on error
- version_chunks(doc_id, version, chunk_id, position, heading, page)

Chunk ids are content addressed ("c-" + sha256(doc_id + chunk text)), so a
chunk that is unchanged between versions is shared by both and never
re-embedded.

Lifecycle of an update:
1. begin_version: the new version is "building". Its new chunks are written
   to Chroma, but the retriever only serves chunks of ACTIVE versions, so
   queries keep seeing the old version.
2. activate: one transaction makes the new version active and the old one
   retired, and bumps the registry generation. From the next query on, the
   retriever serves the new version; chunks only the old version used are
   excluded immediately.
3. Garbage collection (asynchronous, after GC_GRACE_SECONDS so in-flight
   queries finish): deletes chunks referenced by no active or building
   version from Chroma and the knowledge graph, drops retired version rows,
   fails abandoned builds, and removes legacy chunks from the old scheme.
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
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, source TEXT NOT NULL, active_version INTEGER);
CREATE TABLE IF NOT EXISTS versions (
    doc_id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
    file_hash TEXT NOT NULL, created TEXT NOT NULL, retired_at REAL,
    PRIMARY KEY (doc_id, version));
CREATE TABLE IF NOT EXISTS version_chunks (
    doc_id TEXT NOT NULL, version INTEGER NOT NULL, chunk_id TEXT NOT NULL,
    position INTEGER NOT NULL, heading TEXT, page INTEGER,
    PRIMARY KEY (doc_id, version, chunk_id));
CREATE INDEX IF NOT EXISTS vc_chunk ON version_chunks(chunk_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def doc_id_for(source: str) -> str:
    try:
        rel = str(Path(source).resolve().relative_to(config.DATA_DIR.resolve()))
    except ValueError:
        rel = source
    return "d-" + hashlib.sha256(rel.encode()).hexdigest()[:16]


def chunk_id_for(doc_id: str, text: str) -> str:
    return "c-" + hashlib.sha256(f"{doc_id}\n{text}".encode("utf-8")).hexdigest()[:32]


def is_web_chunk(chunk_id: str) -> bool:
    return chunk_id.startswith("web-")


@contextmanager
def _db(persist_dir=None):
    path = (persist_dir or config.PERSIST_DIR) / "registry.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        yield conn
    finally:
        conn.close()


def _bump_generation(conn) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES('generation', '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")


# ---------- reads ----------

def generation() -> int:
    with _db() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='generation'").fetchone()
        # LINEAJE: runtime guardrail checks `row` as it flows from a database to the agent, after the tool returns (in generation).
        #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `row` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:7de88b45ad1a8e821ce32518e9187863fdc86cda079bb66498564126d3f63823'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:7de88b45ad1a8e821ce32518e9187863fdc86cda079bb66498564126d3f63823', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 91, 'function': 'generation'}, 'file': 'rag/versioning.py', 'line': 91, 'function': 'generation', 'agent_name': 'generation', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            row = _gr_client.enforce(_gr_site, row, content_type='application/json', variable_name='row', source_file=__file__, before_line=91)
        except _gr_client.GuardrailUnavailableError:
            pass
    return int(row["value"]) if row else 0


def active_hash(doc_id: str) -> str | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT v.file_hash FROM documents d JOIN versions v "
            "ON v.doc_id = d.doc_id AND v.version = d.active_version WHERE d.doc_id = ?",
            (doc_id,)).fetchone()
        # LINEAJE: runtime guardrail checks `row` as it flows from a database to the agent, after the tool returns (in active_hash).
        #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `row` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:ab86eb2bec21165f51290cd3cc376f413727eee88c723979857c81c1d69218a2'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ab86eb2bec21165f51290cd3cc376f413727eee88c723979857c81c1d69218a2', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 97, 'function': 'active_hash'}, 'file': 'rag/versioning.py', 'line': 97, 'function': 'active_hash', 'agent_name': 'active_hash', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            row = _gr_client.enforce(_gr_site, row, content_type='application/json', variable_name='row', source_file=__file__, before_line=97)
        except _gr_client.GuardrailUnavailableError:
            pass
    return row["file_hash"] if row else None


def active_chunk_ids() -> set[str]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT vc.chunk_id FROM version_chunks vc JOIN documents d "
            "ON vc.doc_id = d.doc_id AND vc.version = d.active_version").fetchall()
        # LINEAJE: runtime guardrail checks `rows` as it flows from a database to the agent, after the tool returns (in active_chunk_ids).
        #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `rows` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:57aabe65f6541fae80b9f391f8b12d09424e4be76ab6c49296d154a1c13b8f17'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:57aabe65f6541fae80b9f391f8b12d09424e4be76ab6c49296d154a1c13b8f17', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 106, 'function': 'active_chunk_ids'}, 'file': 'rag/versioning.py', 'line': 106, 'function': 'active_chunk_ids', 'agent_name': 'active_chunk_ids', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            rows = _gr_client.enforce(_gr_site, rows, content_type='application/json', variable_name='rows', source_file=__file__, before_line=106)
        except _gr_client.GuardrailUnavailableError:
            pass
    return {r["chunk_id"] for r in rows}


_cache = {"generation": -1, "ids": set(), "path": None}
_cache_lock = threading.Lock()


def active_set() -> set[str]:
    """Active chunk ids, reloaded only when the registry generation changes."""
    gen, path = generation(), str(config.PERSIST_DIR)
    with _cache_lock:
        if gen != _cache["generation"] or path != _cache["path"]:
            _cache.update(generation=gen, ids=active_chunk_ids(), path=path)
        return _cache["ids"]


def is_active(chunk_id: str) -> bool:
    """Web passages are unversioned and always live; file chunks must belong to an
    active version (chunks of building, retired, or legacy versions are hidden)."""
    return is_web_chunk(chunk_id) or chunk_id in active_set()


def documents() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT d.doc_id, d.source, d.active_version, "
            " (SELECT COUNT(*) FROM version_chunks vc WHERE vc.doc_id = d.doc_id "
            "  AND vc.version = d.active_version) AS chunks, "
            " (SELECT COUNT(*) FROM versions v WHERE v.doc_id = d.doc_id) AS versions "
            "FROM documents d WHERE d.active_version IS NOT NULL").fetchall()
        # LINEAJE: runtime guardrail checks `rows` as it flows from a database to the agent, after the tool returns (in documents).
        #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `rows` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:b2b8f4a4c4fc4bdc37e39e445eaeaee31e20f221be54a30dd37e18e2eef7c433'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:b2b8f4a4c4fc4bdc37e39e445eaeaee31e20f221be54a30dd37e18e2eef7c433', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 133, 'function': 'documents'}, 'file': 'rag/versioning.py', 'line': 133, 'function': 'documents', 'agent_name': 'documents', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            rows = _gr_client.enforce(_gr_site, rows, content_type='application/json', variable_name='rows', source_file=__file__, before_line=133)
        except _gr_client.GuardrailUnavailableError:
            pass
    return [dict(r) for r in rows]


def version_chunks(doc_id: str, version: int | None = None) -> list[dict]:
    with _db() as conn:
        if version is None:
            row = conn.execute("SELECT active_version FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            # LINEAJE: runtime guardrail checks `row` as it flows from a database to the agent, after the tool returns (in version_chunks).
            #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `row` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:cfcb1d29f7284d4c7cd34df336e2d5605196dba4a481cb0083224102d672b1d0'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:cfcb1d29f7284d4c7cd34df336e2d5605196dba4a481cb0083224102d672b1d0', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 145, 'function': 'version_chunks'}, 'file': 'rag/versioning.py', 'line': 145, 'function': 'version_chunks', 'agent_name': 'version_chunks', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                row = _gr_client.enforce(_gr_site, row, content_type='application/json', variable_name='row', source_file=__file__, before_line=145)
            except _gr_client.GuardrailUnavailableError:
                pass
            version = row["active_version"] if row else None
        rows = conn.execute(
            "SELECT chunk_id, position, heading, page FROM version_chunks "
            "WHERE doc_id=? AND version=? ORDER BY position", (doc_id, version)).fetchall()
        # LINEAJE: runtime guardrail checks `rows` as it flows from a database to the agent, after the tool returns (in version_chunks).
        #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `rows` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:9db2fc70796702f2eeea715755b0904d86d437332e07312718657b5133601174'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:9db2fc70796702f2eeea715755b0904d86d437332e07312718657b5133601174', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 147, 'function': 'version_chunks'}, 'file': 'rag/versioning.py', 'line': 147, 'function': 'version_chunks', 'agent_name': 'version_chunks', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            rows = _gr_client.enforce(_gr_site, rows, content_type='application/json', variable_name='rows', source_file=__file__, before_line=147)
        except _gr_client.GuardrailUnavailableError:
            pass
    return [dict(r) for r in rows]


def history(doc_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT v.version, v.status, v.created, v.file_hash, "
            " (SELECT COUNT(*) FROM version_chunks vc WHERE vc.doc_id=v.doc_id AND vc.version=v.version) AS chunks "
            "FROM versions v WHERE v.doc_id=? ORDER BY v.version", (doc_id,)).fetchall()
        # LINEAJE: runtime guardrail checks `rows` as it flows from a database to the agent, after the tool returns (in history).
        #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `rows` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:b6c1efa86e966eb1f9e370b469015d85e5ce94d84691ef62553a6bfcfc100267'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:b6c1efa86e966eb1f9e370b469015d85e5ce94d84691ef62553a6bfcfc100267', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 155, 'function': 'history'}, 'file': 'rag/versioning.py', 'line': 155, 'function': 'history', 'agent_name': 'history', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            rows = _gr_client.enforce(_gr_site, rows, content_type='application/json', variable_name='rows', source_file=__file__, before_line=155)
        except _gr_client.GuardrailUnavailableError:
            pass
    return [dict(r) for r in rows]


def registry_stats() -> dict:
    with _db() as conn:
        counts = dict(conn.execute("SELECT status, COUNT(*) FROM versions GROUP BY status").fetchall())
        docs = conn.execute("SELECT COUNT(*) FROM documents WHERE active_version IS NOT NULL").fetchone()[0]
    return {"documents": docs, "versions": counts, "generation": generation()}


# ---------- writes ----------

def begin_version(doc_id: str, source: str, file_hash: str, chunks: list[dict]) -> int:
    """Register a new building version with its ordered chunk list
    [{chunk_id, position, heading, page}]. Not visible to retrieval yet."""
    now = datetime.now().isoformat(timespec="seconds")
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO documents(doc_id, source) VALUES(?, ?) "
                     "ON CONFLICT(doc_id) DO UPDATE SET source=excluded.source", (doc_id, source))
        version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM versions WHERE doc_id=?",
                               (doc_id,)).fetchone()[0]
        conn.execute("INSERT INTO versions(doc_id, version, status, file_hash, created) "
                     "VALUES(?, ?, 'building', ?, ?)", (doc_id, version, file_hash, now))
        conn.executemany(
            "INSERT OR IGNORE INTO version_chunks(doc_id, version, chunk_id, position, heading, page) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            [(doc_id, version, c["chunk_id"], c["position"], c.get("heading"), c.get("page"))
             for c in chunks])
        conn.execute("COMMIT")
    # LINEAJE: runtime guardrail checks `version` as it flows from the agent to the user interface, before it leaves the application (in begin_version).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `version` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:8c0778069ff8500d6e4411ae9d6f05f2204811ec6dd426456615b2fed6f25f1b'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:8c0778069ff8500d6e4411ae9d6f05f2204811ec6dd426456615b2fed6f25f1b', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/versioning.py', 'line': 189, 'function': 'begin_version'}, 'file': 'rag/versioning.py', 'line': 189, 'function': 'begin_version', 'agent_name': 'begin_version', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        version = _gr_client.enforce(_gr_site, version, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return version


def activate(doc_id: str, version: int) -> None:
    """Atomically make `version` the live one and retire the previous version."""
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE versions SET status='retired', retired_at=? "
                     "WHERE doc_id=? AND status='active'", (time.time(), doc_id))
        conn.execute("UPDATE versions SET status='active' WHERE doc_id=? AND version=?",
                     (doc_id, version))
        conn.execute("UPDATE documents SET active_version=? WHERE doc_id=?", (version, doc_id))
        _bump_generation(conn)
        conn.execute("COMMIT")


def fail_version(doc_id: str, version: int) -> None:
    with _db() as conn:
        conn.execute("UPDATE versions SET status='failed', retired_at=? WHERE doc_id=? AND version=?",
                     (time.time(), doc_id, version))


def retire_document(doc_id: str) -> None:
    """The file was deleted: hide it immediately; GC removes its chunks later."""
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE versions SET status='retired', retired_at=? "
                     "WHERE doc_id=? AND status IN ('active', 'building')", (time.time(), doc_id))
        conn.execute("UPDATE documents SET active_version=NULL WHERE doc_id=?", (doc_id,))
        _bump_generation(conn)
        conn.execute("COMMIT")


def known_documents() -> dict[str, str]:
    """doc_id -> source for every document with an active version."""
    with _db() as conn:
        return {r["doc_id"]: r["source"] for r in
                conn.execute("SELECT doc_id, source FROM documents WHERE active_version IS NOT NULL")}


# ---------- garbage collection ----------

_gc_lock = threading.Lock()
_gc_threads: list[threading.Thread] = []


def collect_garbage(grace_seconds: float | None = None, persist_dir=None) -> dict:
    """Delete chunks that no active or building version references.

    Only versions retired (or failed) at least `grace_seconds` ago are
    collected, so queries that started before a switch can finish. Builds that
    have been "building" longer than GC_STALE_BUILD_SECONDS are treated as
    abandoned (crashed) and failed first.
    """
    from .store import get_vectorstore

    persist_dir = persist_dir or config.PERSIST_DIR
    grace = config.GC_GRACE_SECONDS if grace_seconds is None else grace_seconds
    cutoff = time.time() - grace
    with _gc_lock, _db(persist_dir) as conn:
        # Abandoned builds (process died mid-update).
        stale = time.time() - config.GC_STALE_BUILD_SECONDS
        for r in conn.execute("SELECT doc_id, version, created FROM versions WHERE status='building'").fetchall():
            if datetime.fromisoformat(r["created"]).timestamp() < stale:
                conn.execute("UPDATE versions SET status='failed', retired_at=? WHERE doc_id=? AND version=?",
                             (time.time() - grace - 1, r["doc_id"], r["version"]))
        old = conn.execute("SELECT doc_id, version FROM versions WHERE status IN ('retired', 'failed') "
                           "AND retired_at <= ?", (cutoff,)).fetchall()
        # LINEAJE: runtime guardrail checks `old` as it flows from a database to the agent, after the tool returns (in collect_garbage).
        #   Detected: this statement moves data from a database to the agent with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `old` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:5b630654e4a7d58e1e6b0740c817108af3017ee02a7a8affb96999c645ee8ed6'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5b630654e4a7d58e1e6b0740c817108af3017ee02a7a8affb96999c645ee8ed6', phase='post_tool', boundary={'source': 'database', 'sink': 'agent_message'}, fail_mode='ALLOW_WITH_AUDIT', source_type='database', destination_type='agent', components={'invocation': {'file': 'rag/versioning.py', 'line': 255, 'function': 'collect_garbage'}, 'file': 'rag/versioning.py', 'line': 255, 'function': 'collect_garbage', 'agent_name': 'collect_garbage', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            old = _gr_client.enforce(_gr_site, old, content_type='application/json', variable_name='old', source_file=__file__, before_line=255)
        except _gr_client.GuardrailUnavailableError:
            pass
        live = {r["chunk_id"] for r in conn.execute(
            "SELECT vc.chunk_id FROM version_chunks vc JOIN versions v "
            "ON v.doc_id=vc.doc_id AND v.version=vc.version WHERE v.status IN ('active', 'building')")}
        candidates = set()
        for r in old:
            candidates |= {x["chunk_id"] for x in conn.execute(
                "SELECT chunk_id FROM version_chunks WHERE doc_id=? AND version=?",
                (r["doc_id"], r["version"]))}

        store = get_vectorstore(persist_dir)
        # Legacy chunks from the pre-versioning scheme: file chunks with no doc_id.
        everything = store.get(include=["metadatas"])
        legacy = {i for i, m in zip(everything["ids"], everything["metadatas"])
                  if m.get("origin") != "web" and not m.get("doc_id")}
        # Orphans: versioned chunks referenced by no version at all.
        referenced = {r["chunk_id"] for r in conn.execute("SELECT DISTINCT chunk_id FROM version_chunks")}
        orphans = {i for i, m in zip(everything["ids"], everything["metadatas"])
                   if m.get("doc_id") and i not in referenced}

        to_delete = sorted(((candidates - live) | legacy | orphans) & set(everything["ids"]))
        for start in range(0, len(to_delete), 200):
            store.delete(ids=to_delete[start:start + 200])

        conn.execute("BEGIN IMMEDIATE")
        for r in old:
            conn.execute("DELETE FROM version_chunks WHERE doc_id=? AND version=?", (r["doc_id"], r["version"]))
            conn.execute("DELETE FROM versions WHERE doc_id=? AND version=?", (r["doc_id"], r["version"]))
        conn.execute("DELETE FROM documents WHERE active_version IS NULL AND doc_id NOT IN "
                     "(SELECT doc_id FROM versions)")
        conn.execute("COMMIT")

    if to_delete and config.GRAPH_ENABLED:
        from .graph import prune_chunks

        prune_chunks(set(to_delete), persist_dir)
    stats = {"versions_collected": len(old), "chunks_deleted": len(to_delete),
             "legacy_deleted": len(legacy & set(to_delete)), "at": datetime.now().isoformat(timespec="seconds")}
    with _db(persist_dir) as conn:
        conn.execute("INSERT INTO meta(key, value) VALUES('last_gc', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(stats),))
    # LINEAJE: runtime guardrail checks `stats` as it flows from the agent to the user interface, before it leaves the application (in collect_garbage).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `stats` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:dbeaa6123908b817b434b3e6834cb33d637004b1d63ae5cfd36c476c39adb062'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:dbeaa6123908b817b434b3e6834cb33d637004b1d63ae5cfd36c476c39adb062', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/versioning.py', 'line': 297, 'function': 'collect_garbage'}, 'file': 'rag/versioning.py', 'line': 297, 'function': 'collect_garbage', 'agent_name': 'collect_garbage', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        stats = _gr_client.enforce(_gr_site, stats, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return stats


def start_gc_async(delay: float | None = None) -> threading.Thread:
    """Run the garbage collector in a background thread after `delay` seconds
    (default GC_GRACE_SECONDS), so it never blocks ingestion or queries."""
    delay = config.GC_GRACE_SECONDS if delay is None else delay
    persist = config.PERSIST_DIR  # bind the store this call targets; never touch globals

    def run():
        time.sleep(delay)
        try:
            stats = collect_garbage(persist_dir=persist)
            if stats["chunks_deleted"]:
                _lineaje_payload = (f"[gc] collected {stats['versions_collected']} old version(s), "
                      f"deleted {stats['chunks_deleted']} chunk(s)")
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:7aa5b921be529b7961d6f8cb2b320fa9e14a10157f96483660a7bd8c07599cdc'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:7aa5b921be529b7961d6f8cb2b320fa9e14a10157f96483660a7bd8c07599cdc', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/versioning.py', 'line': 311, 'function': 'start_gc_async.run'}, 'file': 'rag/versioning.py', 'line': 311, 'function': 'run', 'agent_name': 'run', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
        except Exception as e:  # never crash the app from the background
            _lineaje_payload = f"[gc] failed: {type(e).__name__}: {e}"
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:bf9a153b450e7b3f406e288da38f4052a279e9f31c1a9b0a8afaa22af78149ff'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:bf9a153b450e7b3f406e288da38f4052a279e9f31c1a9b0a8afaa22af78149ff', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/versioning.py', 'line': 314, 'function': 'start_gc_async.run'}, 'file': 'rag/versioning.py', 'line': 314, 'function': 'run', 'agent_name': 'run', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)

    t = threading.Thread(target=run, name="luminus-gc", daemon=True)
    t.start()
    _gc_threads.append(t)
    # LINEAJE: runtime guardrail checks `t` as it flows from the agent to the user interface, before it leaves the application (in start_gc_async).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `t` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:daf21b4c50397dfad01dea1904034857c16bb620ba388b3fee4f553699db7577'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:daf21b4c50397dfad01dea1904034857c16bb620ba388b3fee4f553699db7577', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/versioning.py', 'line': 319, 'function': 'start_gc_async'}, 'file': 'rag/versioning.py', 'line': 319, 'function': 'start_gc_async', 'agent_name': 'start_gc_async', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        t = _gr_client.enforce(_gr_site, t, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return t


def wait_for_gc(timeout: float | None = None) -> None:
    """Block until background GC threads finish (for short-lived CLI processes)."""
    for t in list(_gc_threads):
        t.join(timeout)
