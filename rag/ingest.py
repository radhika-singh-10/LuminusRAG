"""Load documents, split into chunks, embed, and upsert into Chroma.

Ingestion is incremental: every chunk gets a deterministic id derived from the
file's content hash, so unchanged files are skipped, changed files are
re-embedded, and files removed from DATA_DIR are deleted from the index.
"""
import hashlib
import shutil
import time
from collections import defaultdict
from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import config
from .store import get_vectorstore


def load_documents(data_dir: Path) -> list[Document]:
    """Load .pdf, .txt and .md files recursively from data_dir."""
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    docs: list[Document] = []
    docs += DirectoryLoader(
        str(data_dir), glob="**/*.pdf", loader_cls=PyPDFLoader, silent_errors=True
    ).load()
    for pattern in ("**/*.txt", "**/*.md"):
        docs += DirectoryLoader(
            str(data_dir),
            glob=pattern,
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
            silent_errors=True,
        ).load()
    return docs


def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        add_start_index=True,
    )
    return splitter.split_documents(docs)


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    # Chunking settings are part of the hash so changing them re-indexes.
    h.update(f"|{config.CHUNK_SIZE}|{config.CHUNK_OVERLAP}|{config.EMBED_MODEL}".encode())
    return h.hexdigest()


SUPPORTED = {".pdf", ".txt", ".md"}
UPLOAD_DIR_NAME = "uploads"


def save_upload(name: str, data: bytes) -> Path:
    """Write an uploaded file into DATA_DIR/uploads (safe filename) and return its path."""
    safe = Path(name).name
    if Path(safe).suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {safe} (use .pdf, .txt or .md)")
    dest_dir = config.DATA_DIR / UPLOAD_DIR_NAME
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe
    dest.write_bytes(data)
    return dest


def add_files(paths: list[str | Path]) -> dict:
    """Copy files into DATA_DIR/uploads and sync the index (only new/changed files embed)."""
    for p in map(Path, paths):
        if not p.is_file():
            raise FileNotFoundError(p)
        if config.DATA_DIR.resolve() not in p.resolve().parents:
            save_upload(p.name, p.read_bytes())
    return ingest()


def remove_source(source: str) -> int:
    """Delete a file from DATA_DIR (or a stored web page) and its chunks from the index.
    Returns chunks removed."""
    if source.startswith(("http://", "https://")):
        store = get_vectorstore()
        ids = store.get(where={"source": source}, include=[])["ids"]
        if ids:
            store.delete(ids=ids)
        return len(ids)
    path = Path(source).resolve()
    if config.DATA_DIR.resolve() not in path.parents:
        raise ValueError(f"Refusing to delete a file outside {config.DATA_DIR}")
    store = get_vectorstore()
    ids = store.get(where={"source": source}, include=[])["ids"]
    if ids:
        store.delete(ids=ids)
    path.unlink(missing_ok=True)
    return len(ids)


def get_chunks(source: str) -> list[dict]:
    """Stored chunks of one file, in order: [{index, page, text}]."""
    data = get_vectorstore().get(where={"source": source}, include=["documents", "metadatas"])
    rows = [
        {"index": m.get("chunk_index", 0), "page": m.get("page"), "text": t}
        for t, m in zip(data["documents"], data["metadatas"])
    ]
    return sorted(rows, key=lambda r: r["index"])


def list_indexed() -> list[dict]:
    """[{source, name, chunks, pages}] for every file in the index."""
    data = get_vectorstore().get(include=["metadatas"])
    agg: dict[str, dict] = {}
    for meta in data["metadatas"]:
        src = meta.get("source", "unknown")
        web = meta.get("origin") == "web"
        name = f"🌐 {meta.get('title') or src}" if web else Path(src).name
        e = agg.setdefault(src, {"source": src, "name": name, "chunks": 0, "pages": set(),
                                 "origin": "web" if web else "file"})
        e["chunks"] += 1
        if meta.get("page") is not None:
            e["pages"].add(meta["page"])
    out = []
    for e in sorted(agg.values(), key=lambda e: e["name"].lower()):
        e["pages"] = len(e["pages"]) or None
        out.append(e)
    return out


def ingest(rebuild: bool = False, progress=None) -> dict:
    """Sync the vector store with DATA_DIR. Returns counts of what changed.

    progress: optional callback(event: str, info: dict) for UIs. Events:
      "loaded" (files), "skip", "split", "embed" (done, total), "stored", "removed"
    """
    emit = progress or (lambda event, info: None)
    batch_size = 32
    if rebuild and config.PERSIST_DIR.exists():
        shutil.rmtree(config.PERSIST_DIR)

    docs = load_documents(config.DATA_DIR)
    if not docs:
        raise RuntimeError(f"No .pdf/.txt/.md files found in {config.DATA_DIR}")

    by_source: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        by_source[d.metadata["source"]].append(d)
    emit("loaded", {"files": len(by_source)})

    store = get_vectorstore()
    existing = store.get(include=["metadatas"])
    indexed: dict[str, dict] = defaultdict(lambda: {"hash": None, "ids": []})
    for id_, meta in zip(existing["ids"], existing["metadatas"]):
        if meta.get("origin") == "web":  # stored web passages, managed separately
            continue
        entry = indexed[meta.get("source", "")]
        entry["hash"] = meta.get("file_hash")
        entry["ids"].append(id_)

    stats = {"added_files": 0, "updated_files": 0, "unchanged_files": 0,
             "removed_files": 0, "chunks_written": 0, "files": []}

    for source, file_docs in by_source.items():
        digest = file_hash(source)
        old = indexed.get(source)
        if old and old["hash"] == digest:
            stats["unchanged_files"] += 1
            emit("skip", {"source": source})
            continue
        if old and old["ids"]:
            store.delete(ids=old["ids"])
            stats["updated_files"] += 1
        else:
            stats["added_files"] += 1

        t0 = time.time()
        text_pages = [d for d in file_docs if d.page_content.strip()]
        chunks = split_documents(text_pages)
        report = {
            "source": source,
            "pages": len(file_docs) if file_docs[0].metadata.get("page") is not None else None,
            "pages_with_text": len(text_pages),
            "characters": sum(len(d.page_content) for d in text_pages),
            "chunks": len(chunks),
            "avg_chunk_chars": round(sum(len(c.page_content) for c in chunks) / len(chunks)) if chunks else 0,
            "status": "updated" if old and old["ids"] else "added",
        }
        emit("split", report)
        if not chunks:
            print(f"Warning: no extractable text in {source} (scanned PDF? needs OCR)")
            stats.setdefault("empty_files", []).append(source)
        ids = []
        for i, c in enumerate(chunks):
            c.metadata.update({"file_hash": digest, "chunk_index": i})
            ids.append(f"{digest[:16]}-{i}")
        for start in range(0, len(chunks), batch_size):
            store.add_documents(chunks[start:start + batch_size], ids=ids[start:start + batch_size])
            emit("embed", {"source": source, "done": min(start + batch_size, len(chunks)),
                           "total": len(chunks)})
        stats["chunks_written"] += len(chunks)
        report["seconds"] = round(time.time() - t0, 2)
        stats["files"].append(report)
        emit("stored", report)

    for source, entry in indexed.items():
        if source not in by_source and entry["ids"]:
            store.delete(ids=entry["ids"])
            stats["removed_files"] += 1
            emit("removed", {"source": source})

    total = len(store.get(include=[])["ids"])
    print(
        f"Index synced: +{stats['added_files']} new, ~{stats['updated_files']} updated, "
        f"={stats['unchanged_files']} unchanged, -{stats['removed_files']} removed files; "
        f"{stats['chunks_written']} chunks written, {total} chunks total."
    )
    stats["total_chunks"] = total
    return stats
