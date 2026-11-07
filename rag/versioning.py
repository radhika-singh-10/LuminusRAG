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
    return int(row["value"]) if row else 0


def active_hash(doc_id: str) -> str | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT v.file_hash FROM documents d JOIN versions v "
            "ON v.doc_id = d.doc_id AND v.version = d.active_version WHERE d.doc_id = ?",
            (doc_id,)).fetchone()
    return row["file_hash"] if row else None


def active_chunk_ids() -> set[str]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT vc.chunk_id FROM version_chunks vc JOIN documents d "
            "ON vc.doc_id = d.doc_id AND vc.version = d.active_version").fetchall()
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
    return [dict(r) for r in rows]


def version_chunks(doc_id: str, version: int | None = None) -> list[dict]:
    with _db() as conn:
        if version is None:
            row = conn.execute("SELECT active_version FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            version = row["active_version"] if row else None
        rows = conn.execute(
            "SELECT chunk_id, position, heading, page FROM version_chunks "
            "WHERE doc_id=? AND version=? ORDER BY position", (doc_id, version)).fetchall()
    return [dict(r) for r in rows]


def history(doc_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT v.version, v.status, v.created, v.file_hash, "
            " (SELECT COUNT(*) FROM version_chunks vc WHERE vc.doc_id=v.doc_id AND vc.version=v.version) AS chunks "
            "FROM versions v WHERE v.doc_id=? ORDER BY v.version", (doc_id,)).fetchall()
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
                print(f"[gc] collected {stats['versions_collected']} old version(s), "
                      f"deleted {stats['chunks_deleted']} chunk(s)")
        except Exception as e:  # never crash the app from the background
            print(f"[gc] failed: {type(e).__name__}: {e}")

    t = threading.Thread(target=run, name="luminus-gc", daemon=True)
    t.start()
    _gc_threads.append(t)
    return t


def wait_for_gc(timeout: float | None = None) -> None:
    """Block until background GC threads finish (for short-lived CLI processes)."""
    for t in list(_gc_threads):
        t.join(timeout)
