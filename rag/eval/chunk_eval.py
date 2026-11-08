"""Chunking evaluation: function-level code chunks vs character splitters,
edit locality (why no overlap), and the debounced sync.

1. Code retrieval. This repo's own modules are chunked three ways:
   - function-level (rag/code_chunking.py): imports / function / class / method, no overlap
   - fixed-size: RecursiveCharacterTextSplitter(1000, overlap 150), the usual default
   - language-aware: RecursiveCharacterTextSplitter.from_language(PYTHON, 1000, overlap 0)
   Questions name a behaviour ("How is the unbiased pass@k estimator
   computed?") and expect the chunk holding that function. Metrics: hit@1,
   hit@3, MRR (a hit is a chunk containing the function's `def` line),
   complete@1 (the top hit holds the whole function), chunk count, and
   duplicated text from overlap.
2. Edit locality. For each function in the corpus: change one line inside it,
   and separately insert a new function at the top of its file. Count how many
   chunk hashes change. Fewer changed chunks = less re-embedding and a smaller
   new version.
3. Debounced sync. A sandbox data folder is indexed, then one file is saved
   three times, two seconds apart, and a Markdown file is edited once. The
   watcher (DEBOUNCE_SECONDS quiet period) must run one sync after the
   last save, with a chunk diff showing only the edited chunks.
"""
import ast
import json
import random
import shutil
import statistics
import tempfile
import time
from pathlib import Path

import numpy as np

from .. import config
from .latency import latency_stats

CORPUS = ["rag/eval/metrics.py", "rag/store.py", "rag/agent/harness.py", "rag/agent/followups.py",
          "rag/agent/personalize.py", "rag/ocr.py", "rag/ingest.py", "rag/intent.py", "rag/followup.py",
          "rag/web.py", "rag/chain.py", "rag/watcher.py", "rag/prompt_cache.py"]

QUESTIONS = [
    ("How is the unbiased pass@k estimator computed?", "pass_at_k"),
    ("How is pass^k, the chance that all k samples are correct, computed?", "pass_hat_k"),
    ("How are Chroma distances converted to cosine similarity?", "distance_to_cosine"),
    ("How does the agent enforce the maximum number of steps in a conversation?", "_memory"),
    ("How are follow-up question candidates filtered and ranked?", "suggest"),
    ("How is the interest profile vector computed from interest entities?", "profile_vector"),
    ("How is personalized PageRank run over the knowledge graph?", "personalized_pagerank"),
    ("How are OCR boxes put back into reading order with paragraph breaks?", "layout_text"),
    ("Which PDF pages get OCR and how is the OCR text attached?", "apply_ocr"),
    ("How does the intent gate decide that a word like guardrail has an AI meaning?", "ai_sense"),
    ("How is a follow-up question rewritten into a standalone question?", "standalone_question"),
    ("How are citations in an answer checked?", "citation_metrics"),
    ("How does web search add AI context to ambiguous queries?", "search_query"),
    ("How are web pages fetched, cleaned and ranked into passages?", "web_documents"),
    ("How is the file hash for document versioning computed?", "file_hash"),
    ("How is the streamed answer sanitized segment by segment?", "_stream_answer"),
    ("How does the debouncer decide a batch of changed files is ready?", "ready"),
    ("How are the system prompts prefilled into the Ollama prompt cache?", "warm"),
]


def _functions(src: str) -> dict[str, str]:
    """{name: full source} for every function / method in a Python file."""
    tree, lines = ast.parse(src), src.splitlines()
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            out.setdefault(node.name, "\n".join(lines[start:node.end_lineno]))
    return out


def _strategies():
    from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

    from ..chunking import chunk_code

    fixed = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    lang = RecursiveCharacterTextSplitter.from_language(Language.PYTHON, chunk_size=1000, chunk_overlap=0)
    return {
        "function-level (ours)": lambda src, name: [c.text for c in chunk_code(src, "python", name)],
        "fixed 1000 / overlap 150": lambda src, name: fixed.split_text(src),
        "LangChain Python splitter": lambda src, name: lang.split_text(src),
    }


def _code_retrieval(files: dict[str, str]) -> dict:
    from ..store import get_embeddings

    emb = get_embeddings()
    funcs = {k: v for src in files.values() for k, v in _functions(src).items()}
    qv = np.asarray(emb.embed_documents([q for q, _ in QUESTIONS]))
    out = {}
    total_chars = sum(len(s) for s in files.values())
    for label, split in _strategies().items():
        chunk_ms, chunks = [], []
        for name, src in files.items():
            t1 = time.perf_counter()
            chunks += split(src, Path(name).name)
            chunk_ms.append((time.perf_counter() - t1) * 1000)
        t1 = time.perf_counter()
        cv = np.asarray(emb.embed_documents(chunks))
        embed_ms = (time.perf_counter() - t1) * 1000
        ranks, complete, query_ms = [], [], []
        for i, (q, sym) in enumerate(QUESTIONS):
            t1 = time.perf_counter()
            order = np.argsort(-(cv @ np.asarray(emb.embed_query(q))))
            query_ms.append((time.perf_counter() - t1) * 1000)
            pos = next((r for r, j in enumerate(order) if f"def {sym}(" in chunks[j]), None)
            ranks.append(pos)
            body = funcs.get(sym, "")
            complete.append(float(pos == 0 and body.strip() in chunks[order[0]]))
        body_chars = sum(len(c.partition("\n\n")[2]) if label.startswith("function") else len(c)
                         for c in chunks)
        out[label] = {
            "chunks": len(chunks),
            "hit@1": round(statistics.fmean(float(r == 0) for r in ranks), 3),
            "hit@3": round(statistics.fmean(float(r is not None and r < 3) for r in ranks), 3),
            "mrr": round(statistics.fmean(1 / (r + 1) if r is not None else 0.0 for r in ranks), 3),
            "complete@1": round(statistics.fmean(complete), 3),
            "duplicated_text": round(max(0.0, body_chars / total_chars - 1), 3),
            "chunk_ms_per_file": latency_stats(chunk_ms),
            "embed_ms_per_chunk": round(embed_ms / max(1, len(chunks)), 2),
            "query_ms": latency_stats(query_ms),
        }
    return out


def _edit_locality(files: dict[str, str], samples: int = 40, seed: int = 0) -> dict:
    """Mean chunks whose hash changes per edit, per strategy."""
    import hashlib

    rnd = random.Random(seed)

    def hashes(chunks):
        return {hashlib.sha256(c.encode()).hexdigest() for c in chunks}

    edits = []
    for name, src in files.items():
        for fname, body in _functions(src).items():
            lines = body.splitlines()
            if len(lines) >= 3 and body in src:
                edits.append((name, src, body, lines))
    rnd.shuffle(edits)
    edits = edits[:samples]
    out = {}
    for label, split in _strategies().items():
        inside, top = [], []
        for name, src, body, lines in edits:
            before = hashes(split(src, Path(name).name))
            k = len(lines) // 2  # change one line in the middle of the function
            changed = "\n".join(lines[:k] + [lines[k] + "  # edited"] + lines[k + 1:])
            inside.append(len(hashes(split(src.replace(body, changed, 1), Path(name).name)) - before))
            # insert a new function after the imports (shifts every later line)
            first_def = src.find("\ndef ")
            if first_def > 0:
                new_src = src[:first_def] + "\n\ndef _new_helper():\n    return None\n" + src[first_def:]
                top.append(len(hashes(split(new_src, Path(name).name)) - before))
        out[label] = {"edit_inside_function": round(statistics.fmean(inside), 2),
                      "insert_function_above": round(statistics.fmean(top), 2) if top else None,
                      "edits": len(inside)}
    return out


def _debounced_sync(quiet: float | None = None) -> dict:
    """Real ingestion in a sandbox: 3 saves of one file + 1 Markdown edit -> one sync."""
    from ..ingest import ingest
    from ..watcher import Watcher
    from .harness import overrides
    from .ocr_eval import sandbox

    quiet = config.DEBOUNCE_SECONDS if quiet is None else quiet
    tmp = Path(tempfile.mkdtemp(prefix="debounce-eval-"))
    data, store = tmp / "data", tmp / "store"
    data.mkdir()
    code, md = data / "metrics.py", data / "vector_databases.md"
    shutil.copy(config.ROOT / "rag" / "eval" / "metrics.py", code)
    shutil.copy(config.DATA_DIR / "vector_databases.md", md)
    events = []
    try:
        with sandbox(data, store), overrides({"GUARD_LLM": False}):
            first = ingest()
            w = Watcher(data, quiet=quiet, max_wait=quiet * 6, poll=0.25,
                        on_event=lambda e, i: events.append((time.time(), e, i)))
            src = code.read_text()
            saves = [src.replace("1.0 - math.comb", "1 - math.comb", 1),
                     src.replace("1.0 - math.comb", "1.00 - math.comb", 1),
                     src.replace("1.0 - math.comb", "1.000 - math.comb", 1)]
            t_last = None
            for i, version in enumerate(saves):
                code.write_text(version)
                if i == 1:
                    md.write_text(md.read_text().replace("Approximate nearest neighbour",
                                                         "Approximate nearest-neighbour", 1))
                t_last = time.time()
                w.step()
                time.sleep(2)
            deadline = time.time() + quiet * 3
            result = None
            while time.time() < deadline and result is None:
                result = w.step()
                time.sleep(0.25)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    starts = [t for t, e, _ in events if e == "sync_start"]
    diffs = {Path(i["source"]).name: {k: i[k] for k in ("total", "unchanged", "added", "removed")}
             for _, e, i in events if e == "diff"}
    done = [t for t, e, _ in events if e == "sync_done"]
    return {
        "debounce_seconds": quiet, "saves": len(saves) + 1, "syncs": len(starts),
        "wait_after_last_save_s": round(starts[0] - t_last, 1) if starts else None,
        "versions_built": sum(1 for _, e, _ in events if e == "activated"),
        "versions_without_debounce": len(saves) + 1,
        "diff": diffs,
        "sync_ms": round((done[0] - starts[0]) * 1000) if starts and done else None,
        "change_to_live_s": round(done[0] - t_last, 1) if done else None,
        "chunks_embedded": (result or {}).get("stats", {}).get("chunks_written"),
        "chunks_reused": (result or {}).get("stats", {}).get("chunks_reused"),
        "initial_chunks": first.get("chunks_written"),
    }


def run_chunk_eval(verbose: bool = True, sync: bool = True) -> dict:
    t0 = time.perf_counter()
    files = {p: (config.ROOT / p).read_text() for p in CORPUS}
    out = {"corpus": CORPUS, "questions": len(QUESTIONS)}
    out["retrieval"] = _code_retrieval(files)
    out["edit_locality"] = _edit_locality(files)
    if verbose:
        print(f"\nCode retrieval ({len(QUESTIONS)} questions over {len(CORPUS)} modules)")
        print(f"  {'strategy':<28}{'chunks':>7}{'hit@1':>7}{'hit@3':>7}{'MRR':>7}{'whole fn':>9}{'dup text':>9}")
        for k, r in out["retrieval"].items():
            print(f"  {k:<28}{r['chunks']:>7}{r['hit@1']:>7.3f}{r['hit@3']:>7.3f}{r['mrr']:>7.3f}"
                  f"{r['complete@1']:>9.3f}{r['duplicated_text']:>9.3f}")
        print("  latency: " + "; ".join(
            f"{k.split(' ')[0]} chunk p50 {r['chunk_ms_per_file']['p50']} ms/file, "
            f"query p50 {r['query_ms']['p50']} ms" for k, r in out["retrieval"].items()))
        print("\nEdit locality (chunks whose hash changes per edit)")
        for k, r in out["edit_locality"].items():
            print(f"  {k:<28} edit inside a function: {r['edit_inside_function']:<5}  "
                  f"insert a function above: {r['insert_function_above']}  ({r['edits']} edits)")
    if sync:
        out["debounce"] = _debounced_sync()
        if verbose:
            d = out["debounce"]
            print(f"\nDebounced sync ({d['debounce_seconds']:g} s): {d['saves']} saves -> {d['syncs']} sync, "
                  f"{d['wait_after_last_save_s']} s after the last save; {d['versions_built']} versions built "
                  f"(vs {d['versions_without_debounce']} without debounce)")
            for f, x in d["diff"].items():
                print(f"  diff {f}: {x['total']} chunks, {x['unchanged']} unchanged, "
                      f"{x['added']} new/changed, {x['removed']} removed")
            print(f"  embedded {d['chunks_embedded']}, reused {d['chunks_reused']}; sync took "
                  f"{d['sync_ms']} ms; last save -> live in {d['change_to_live_s']} s")
    out["seconds"] = round(time.perf_counter() - t0, 1)
    path = config.EVAL_RESULTS_DIR / f"chunking-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))
    out["path"] = str(path)
    return out
