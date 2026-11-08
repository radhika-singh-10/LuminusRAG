"""Versioned, content-addressed ingestion.

For every file in DATA_DIR:
1. Unchanged files (same file hash as the active version) are skipped.
2. New or changed files are OCR'd where a PDF page has no text layer
   (rag/ocr.py), policy-sanitized and split by structure
   (headings, sections, paragraphs; see rag/chunking.py).
3. Each chunk id is a hash of its content, so chunks that did not change keep
   their id and embedding; only new chunks are embedded.
4. The chunks form a new document version that stays "building" (invisible to
   retrieval, which keeps serving the old version) until it is complete,
   including its knowledge-graph facts. Then it is activated atomically and
   the previous version is retired.
5. Deleted files are retired. A background garbage collector later deletes
   chunks that no live version uses (see rag/versioning.py).
"""
import hashlib
import shutil
import threading
import time
from collections import defaultdict
from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document

from . import config
from . import versioning as V
from .chunking import chunk_code, chunk_text
from .code_chunking import language_for
from .policy import sanitize_document
from .store import get_vectorstore

CHUNKER_VERSION = "structure-v2"  # v2: code chunked by function / class
OCR_VERSION = "rapidocr-v1"
from .code_chunking import LANGUAGES

TEXT_TYPES = {".txt", ".md"}
SUPPORTED = {".pdf"} | TEXT_TYPES | set(LANGUAGES)
UPLOAD_DIR_NAME = "uploads"


def load_documents(data_dir: Path, only: set[str] | None = None) -> list[Document]:
    """Load .pdf, .txt, .md and source-code files recursively from data_dir
    (only the given absolute paths, if `only` is set)."""
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    docs: list[Document] = []
    for path in sorted(data_dir.rglob("*")):
        ext = path.suffix.lower()
        if not path.is_file() or ext not in SUPPORTED or path.name.startswith("."):
            continue
        if only is not None and str(path.resolve()) not in only:
            continue
        try:
            if ext == ".pdf":
                docs += PyPDFLoader(str(path)).load()
            else:
                docs += TextLoader(str(path), encoding="utf-8").load()
        except Exception as e:  # unreadable file: skip it, keep going
            print(f"Warning: could not load {path}: {type(e).__name__}: {e}")
    return docs


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    # Chunking settings are part of the hash so changing them creates new versions.
    h.update(f"|{CHUNKER_VERSION}|{config.CHUNK_SIZE}|{config.EMBED_MODEL}".encode())
    # Policy changes re-version everything, so stored text always matches current rules.
    for policy in sorted((config.ROOT / "policies").glob("*.json")):
        h.update(policy.read_bytes())
    h.update(f"|guard_llm={config.GUARD_LLM}".encode())
    if str(path).lower().endswith(".pdf"):  # OCR settings change what a scanned PDF yields
        h.update(f"|ocr={config.OCR_ENABLED}:{OCR_VERSION}:{config.OCR_DPI}:"
                 f"{config.OCR_MIN_CHARS}:{config.OCR_MIN_CONFIDENCE}".encode())
    return h.hexdigest()


def apply_ocr(source: str, file_docs: list[Document], emit=None) -> dict:
    """OCR the pages of a PDF that have (almost) no text layer, in place.
    Returns {"pages": [...], "confidence": mean or None, "seconds": total}."""
    from .ocr import needs_ocr, ocr_pdf_pages

    info = {"pages": [], "confidence": None, "seconds": 0.0}
    if not (config.OCR_ENABLED and source.lower().endswith(".pdf")):
        return info
    by_page = {d.metadata.get("page"): d for d in file_docs if d.metadata.get("page") is not None}
    todo = sorted(p for p, d in by_page.items() if needs_ocr(d.page_content))
    if not todo:
        return info
    if emit:
        emit("ocr", {"source": source, "done": 0, "total": len(todo)})
    results = ocr_pdf_pages(source, todo, progress=lambda i, n: emit and emit(
        "ocr", {"source": source, "done": i, "total": n}))
    confs = []
    for page, r in results.items():
        info["seconds"] += r.seconds
        if r.text.strip():
            d = by_page[page]
            d.page_content = r.text
            d.metadata.update(ocr=True, ocr_confidence=r.confidence)
            info["pages"].append(page)
            confs.append(r.confidence)
    if confs:
        info["confidence"] = round(sum(confs) / len(confs), 4)
    info["seconds"] = round(info["seconds"], 1)
    return info


def save_upload(name: str, data: bytes) -> Path:
    """Write an uploaded file into DATA_DIR/uploads (safe filename) and return its path."""
    safe = Path(name).name
    if Path(safe).suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {safe} (use .pdf, .txt, .md or a source file: "
                         f"{', '.join(sorted(LANGUAGES))})")
    dest_dir = config.DATA_DIR / UPLOAD_DIR_NAME
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe
    dest.write_bytes(data)
    return dest


def add_files(paths: list[str | Path]) -> dict:
    """Copy files into DATA_DIR/uploads and sync the index (only new/changed chunks embed)."""
    for p in map(Path, paths):
        if not p.is_file():
            raise FileNotFoundError(p)
        if config.DATA_DIR.resolve() not in p.resolve().parents:
            save_upload(p.name, p.read_bytes())
    return ingest()


def remove_source(source: str) -> int:
    """Remove a file (retire its document; GC deletes the chunks) or a stored web page.
    Returns the number of chunks taken out of service."""
    store = get_vectorstore()
    if source.startswith(("http://", "https://")):
        ids = store.get(where={"source": source}, include=[])["ids"]
        if ids:
            store.delete(ids=ids)
            if config.GRAPH_ENABLED:
                from .graph import prune_chunks

                prune_chunks(set(ids))
        return len(ids)
    path = Path(source).resolve()
    if config.DATA_DIR.resolve() not in path.parents:
        raise ValueError(f"Refusing to delete a file outside {config.DATA_DIR}")
    doc_id = V.doc_id_for(source)
    n = len(V.version_chunks(doc_id))
    V.retire_document(doc_id)
    path.unlink(missing_ok=True)
    V.start_gc_async()
    return n


def get_chunks(source: str) -> list[dict]:
    """Chunks of a file's active version (or a web page), in order:
    [{index, page, heading, text, chunk_id}]."""
    store = get_vectorstore()
    if source.startswith(("http://", "https://")):
        data = store.get(where={"source": source}, include=["documents", "metadatas"])
        return [{"index": i, "page": None, "heading": m.get("title", ""), "text": t, "chunk_id": cid}
                for i, (cid, t, m) in enumerate(zip(data["ids"], data["documents"], data["metadatas"]))]
    rows = V.version_chunks(V.doc_id_for(source))
    if not rows:
        return []
    data = store.get(ids=[r["chunk_id"] for r in rows], include=["documents"])
    text = dict(zip(data["ids"], data["documents"]))
    return [{"index": r["position"], "page": r["page"], "heading": r["heading"] or "",
             "text": text.get(r["chunk_id"], ""), "chunk_id": r["chunk_id"]} for r in rows]


def list_indexed() -> list[dict]:
    """[{source, name, chunks, pages, origin, versions}] for live files and web pages."""
    out = []
    for d in V.documents():
        rows = V.version_chunks(d["doc_id"])
        pages = {r["page"] for r in rows if r["page"] is not None}
        out.append({"source": d["source"], "name": Path(d["source"]).name, "chunks": d["chunks"],
                    "pages": len(pages) or None, "origin": "file", "doc_id": d["doc_id"],
                    "version": d["active_version"], "versions": d["versions"]})
    web = get_vectorstore().get(where={"origin": "web"}, include=["metadatas"])
    agg: dict[str, dict] = {}
    for meta in web["metadatas"]:
        src = meta.get("source", "unknown")
        e = agg.setdefault(src, {"source": src, "name": f"🌐 {meta.get('title') or src}",
                                 "chunks": 0, "pages": None, "origin": "web"})
        e["chunks"] += 1
    out += agg.values()
    return sorted(out, key=lambda e: e["name"].lower())


def _chunk_document(file_docs: list[Document]) -> list:
    chunks = []
    for d in sorted(file_docs, key=lambda d: d.metadata.get("page") or 0):
        if d.page_content.strip():
            chunks += chunk_text(d.page_content, page=d.metadata.get("page"), start=len(chunks))
    return chunks


def _chunk_code_file(source: str, text: str, sanitized: dict) -> list:
    """Code: chunk the original source by syntax first (sanitizing first could
    remove lines and break parsing), then sanitize each chunk's code."""
    language = language_for(source)
    chunks = chunk_code(text, language, Path(source).name)
    for c in chunks:
        heading, _, body = c.text.partition("\n\n")
        clean, rep = sanitize_document(body)
        sanitized["dropped"] += rep["dropped_paragraphs"]
        sanitized["redacted"] |= set(rep["redacted"])
        c.text = f"{heading}\n\n{clean}"
    return [c for c in chunks if c.text.partition("\n\n")[2].strip()]


_INGEST_LOCK = threading.RLock()  # the watcher thread and UI uploads never index at once


def ingest(rebuild: bool = False, progress=None, only: set[str] | None = None) -> dict:
    with _INGEST_LOCK:
        return _ingest(rebuild, progress, only)


def _ingest(rebuild: bool = False, progress=None, only: set[str] | None = None) -> dict:
    """Sync the vector store with DATA_DIR using versioned, content-addressed chunks.

    only: absolute paths to sync (the debounced watcher passes the files that
    changed); other files are left alone. A path in `only` that no longer
    exists is retired.

    progress: optional callback(event: str, info: dict) for UIs. Events:
      "loaded", "skip", "ocr", "sanitized", "diff", "split", "embed", "graph",
      "graph_progress", "activated", "stored", "removed", "gc_scheduled"
    """
    emit = progress or (lambda event, info: None)
    batch_size = 32
    if rebuild and config.PERSIST_DIR.exists():
        shutil.rmtree(config.PERSIST_DIR)

    if only is not None:
        only = {str(Path(p).resolve()) for p in only}
    docs = load_documents(config.DATA_DIR, only)
    if not docs and only is None:
        raise RuntimeError(f"No supported files found in {config.DATA_DIR}")
    by_source: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        by_source[d.metadata["source"]].append(d)
    emit("loaded", {"files": len(by_source)})

    store = get_vectorstore()
    known = V.known_documents()
    stats = {"added_files": 0, "updated_files": 0, "unchanged_files": 0, "removed_files": 0,
             "failed_files": 0, "chunks_written": 0, "chunks_reused": 0, "files": []}
    seen_docs = set()

    for source, file_docs in by_source.items():
        doc_id = V.doc_id_for(source)
        seen_docs.add(doc_id)
        digest = file_hash(source)
        if V.active_hash(doc_id) == digest:
            stats["unchanged_files"] += 1
            emit("skip", {"source": source})
            continue
        status = "updated" if doc_id in known else "added"
        t0 = time.time()

        # Scanned pages: OCR before the policy check, so OCR text is sanitized too.
        ocr = apply_ocr(source, file_docs, emit)

        # Security: drop prompt-injection passages and redact PII before anything
        # is embedded or stored (policies/prompt_injection.json, policies/pii.json).
        sanitized = {"dropped": [], "redacted": set(), "hidden": 0}
        is_code = language_for(source) is not None
        if is_code:
            chunks = _chunk_code_file(source, file_docs[0].page_content, sanitized)
        else:
            for d in file_docs:
                d.page_content, rep = sanitize_document(d.page_content)
                sanitized["dropped"] += rep["dropped_paragraphs"]
                sanitized["redacted"] |= set(rep["redacted"])
                sanitized["hidden"] += rep["html_comments"] + rep["images"]
            chunks = _chunk_document(file_docs)
        emit("sanitized", {"source": source, "dropped": sanitized["dropped"],
                           "redacted": sorted(sanitized["redacted"]), "hidden": sanitized["hidden"]})

        # Chunks by structure (headings / paragraphs, or functions / classes for
        # code) with content-addressed ids: no overlap, so an edit changes only
        # the chunks it touches.
        records, unique = [], {}
        for c in chunks:
            cid = V.chunk_id_for(doc_id, c.text)
            if cid in unique:  # identical chunk twice in one document: store once
                continue
            unique[cid] = c
            records.append({"chunk_id": cid, "position": len(records), "heading": c.heading,
                            "page": c.page})
        ids = [r["chunk_id"] for r in records]
        existing = set(store.get(ids=ids, include=[])["ids"]) if ids else set()
        new_ids = [i for i in ids if i not in existing]
        previous = {r["chunk_id"] for r in V.version_chunks(doc_id)} if doc_id in known else set()
        diff = {"source": source, "total": len(ids), "unchanged": len(set(ids) & previous),
                "added": len(set(ids) - previous), "removed": len(previous - set(ids))}
        emit("diff", diff)
        text_pages = [d for d in file_docs if d.page_content.strip()]
        report = {
            "source": source, "status": status,
            "pages": len(file_docs) if file_docs[0].metadata.get("page") is not None else None,
            "pages_with_text": len(text_pages),
            "characters": sum(len(d.page_content) for d in text_pages),
            "chunks": len(records), "reused": len(records) - len(new_ids), "embedded": len(new_ids),
            "avg_chunk_chars": round(sum(len(unique[i].text) for i in ids) / len(ids)) if ids else 0,
            "injections_removed": len(sanitized["dropped"]), "hidden_removed": sanitized["hidden"],
            "pii_redacted": ", ".join(sorted(sanitized["redacted"])) or "-",
            "ocr_pages": len(ocr["pages"]), "ocr_confidence": ocr["confidence"],
            "changed_chunks": diff["added"], "removed_chunks": diff["removed"],
        }
        emit("split", report)
        if not records:
            print(f"Warning: no extractable text in {source}"
                  + (" (even after OCR)" if config.OCR_ENABLED else " (scanned PDF? set OCR_ENABLED=true)"))
            stats.setdefault("empty_files", []).append(source)

        # New version: building (invisible) until everything below succeeds.
        ocr_pages = set(ocr["pages"])
        version = V.begin_version(doc_id, source, digest, records)
        report["version"] = version
        try:
            for start in range(0, len(new_ids), batch_size):
                batch = new_ids[start:start + batch_size]
                store.add_documents(
                    [Document(page_content=unique[i].text, metadata={
                        "source": source, "doc_id": doc_id, "content_hash": unique[i].content_hash,
                        "heading": unique[i].heading,
                        **({"page": unique[i].page} if unique[i].page is not None else {}),
                        **({"ocr": True} if unique[i].page in ocr_pages else {}),
                        **{k: v for k, v in unique[i].meta.items() if v}})
                     for i in batch], ids=batch)
                emit("embed", {"source": source, "done": min(start + batch_size, len(new_ids)),
                               "total": len(new_ids)})
            if config.GRAPH_ENABLED and new_ids:
                from .graph import update_graph

                emit("graph", {"source": source, "message": "Updating knowledge graph…"})
                update_graph(progress=lambda i, n: emit("graph_progress", {"done": i, "total": n}))
            V.activate(doc_id, version)
        except Exception:
            V.fail_version(doc_id, version)  # old version stays live; GC cleans up
            stats["failed_files"] += 1
            raise
        emit("activated", {"source": source, "version": version})

        stats["added_files" if status == "added" else "updated_files"] += 1
        stats["chunks_written"] += len(new_ids)
        stats["chunks_reused"] += len(records) - len(new_ids)
        report["seconds"] = round(time.time() - t0, 2)
        stats["files"].append(report)
        emit("stored", report)

    for doc_id, source in known.items():
        if only is not None and str(Path(source).resolve()) not in only:
            continue  # not part of this sync
        if doc_id not in seen_docs:
            V.retire_document(doc_id)
            stats["removed_files"] += 1
            emit("removed", {"source": source})

    if stats["updated_files"] or stats["removed_files"] or rebuild or _has_legacy(store):
        V.start_gc_async()
        emit("gc_scheduled", {"delay": config.GC_GRACE_SECONDS})
        stats["gc_scheduled"] = True

    live_files = sum(d["chunks"] for d in V.documents())
    web = len(store.get(where={"origin": "web"}, include=[])["ids"])
    stats["total_chunks"] = live_files + web
    print(
        f"Index synced: +{stats['added_files']} new, ~{stats['updated_files']} updated, "
        f"={stats['unchanged_files']} unchanged, -{stats['removed_files']} removed files; "
        f"{stats['chunks_written']} chunks embedded, {stats['chunks_reused']} reused; "
        f"{stats['total_chunks']} live chunks."
    )
    return stats


def _has_legacy(store) -> bool:
    """True if chunks from the pre-versioning scheme are still stored."""
    meta = store.get(include=["metadatas"])["metadatas"]
    return any(m.get("origin") != "web" and not m.get("doc_id") for m in meta)
