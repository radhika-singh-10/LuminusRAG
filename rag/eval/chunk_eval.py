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
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in _functions).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:6ad0570309ac02b7d1e78dd0652b5b65fdb640896b79b8eded74dcd42f609f7a'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:6ad0570309ac02b7d1e78dd0652b5b65fdb640896b79b8eded74dcd42f609f7a', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 70, 'function': '_functions'}, 'file': 'rag/eval/chunk_eval.py', 'line': 70, 'function': '_functions', 'agent_name': '_functions', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
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
    _lineaje_payload = [q for q, _ in QUESTIONS]
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in _code_retrieval).
    #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `_lineaje_payload` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:fe9825ab8f5bf317923f2e754872cd9a15928eed963a684bb8ffd4763e35afaf'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:fe9825ab8f5bf317923f2e754872cd9a15928eed963a684bb8ffd4763e35afaf', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 92, 'function': '_code_retrieval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 92, 'function': '_code_retrieval', 'agent_name': '_code_retrieval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=92)
    except _gr_client.GuardrailUnavailableError:
        pass
    qv = np.asarray(emb.embed_documents(_lineaje_payload))
    out = {}
    total_chars = sum(len(s) for s in files.values())
    for label, split in _strategies().items():
        chunk_ms, chunks = [], []
        for name, src in files.items():
            t1 = time.perf_counter()
            chunks += split(src, Path(name).name)
            chunk_ms.append((time.perf_counter() - t1) * 1000)
        t1 = time.perf_counter()
        # LINEAJE: runtime guardrail checks `chunks` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in _code_retrieval).
        #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `chunks` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:033e4a17dca860d4023034242c7e52b3b6197c32defcd02ebea561bb4b3f9612'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:033e4a17dca860d4023034242c7e52b3b6197c32defcd02ebea561bb4b3f9612', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 102, 'function': '_code_retrieval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 102, 'function': '_code_retrieval', 'agent_name': '_code_retrieval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            chunks = _gr_client.enforce(_gr_site, chunks, content_type='application/json', variable_name='chunks', source_file=__file__, before_line=102)
        except _gr_client.GuardrailUnavailableError:
            pass
        cv = np.asarray(emb.embed_documents(chunks))
        embed_ms = (time.perf_counter() - t1) * 1000
        ranks, complete, query_ms = [], [], []
        for i, (q, sym) in enumerate(QUESTIONS):
            t1 = time.perf_counter()
            # LINEAJE: runtime guardrail checks `q` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in _code_retrieval).
            #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `q` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:d0bd6c0c1a83f6f36e064339899e023975e40cb206738307d149eabbb33d3162'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:d0bd6c0c1a83f6f36e064339899e023975e40cb206738307d149eabbb33d3162', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 107, 'function': '_code_retrieval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 107, 'function': '_code_retrieval', 'agent_name': '_code_retrieval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                q = _gr_client.enforce(_gr_site, q, content_type='application/json', variable_name='q', source_file=__file__, before_line=107)
            except _gr_client.GuardrailUnavailableError:
                pass
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
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in _code_retrieval).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:cad6384dcb24d49bfd2cd48e9fa20561d68e42c3707b8687f90903ef90f3d338'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:cad6384dcb24d49bfd2cd48e9fa20561d68e42c3707b8687f90903ef90f3d338', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 126, 'function': '_code_retrieval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 126, 'function': '_code_retrieval', 'agent_name': '_code_retrieval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
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
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in _edit_locality).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:be62423d9902b35dedd44d493910a4864887fab921a1555983847e28d240a9cd'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:be62423d9902b35dedd44d493910a4864887fab921a1555983847e28d240a9cd', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 162, 'function': '_edit_locality'}, 'file': 'rag/eval/chunk_eval.py', 'line': 162, 'function': '_edit_locality', 'agent_name': '_edit_locality', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
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
                # LINEAJE: runtime guardrail checks `version` as it flows from the agent to a file, before it is written to disk (in _debounced_sync).
                #   Detected: this statement moves data from the agent to a file with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_025; sensitive values in `version` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:ac29bb949895d43f710456d185e397a9688b5cd7062a1c526d902de802d56301'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:ac29bb949895d43f710456d185e397a9688b5cd7062a1c526d902de802d56301', phase='file_write', boundary={'source': 'agent_message', 'sink': 'file_content'}, fail_mode='BLOCK', source_type='agent', destination_type='file', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 191, 'function': '_debounced_sync'}, 'file': 'rag/eval/chunk_eval.py', 'line': 191, 'function': '_debounced_sync', 'agent_name': '_debounced_sync', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    version = _gr_client.enforce(_gr_site, version, content_type='application/json', variable_name='version', source_file=__file__, before_line=191)
                except _gr_client.GuardrailUnavailableError:
                    pass
                code.write_text(version)
                if i == 1:
                    _lineaje_payload = (md.read_text().replace("Approximate nearest neighbour",
                                                         "Approximate nearest-neighbour", 1))
                    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to a file, before it is written to disk (in _debounced_sync).
                    #   Detected: this statement moves data from the agent to a file with no runtime policy check (detection confidence: high).
                    #   Decision: the Guardrail evaluates AI_DAT_SEC_025; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                    #   Do not remove without review. site_id='site:sha256:56714d723a4957a90ec398db04f0a0bd320e94f2edc7a00623055a1c1f09243c'
                    _gr_client = _lineaje_load_gr_client()
                    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:56714d723a4957a90ec398db04f0a0bd320e94f2edc7a00623055a1c1f09243c', phase='file_write', boundary={'source': 'agent_message', 'sink': 'file_content'}, fail_mode='BLOCK', source_type='agent', destination_type='file', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 193, 'function': '_debounced_sync'}, 'file': 'rag/eval/chunk_eval.py', 'line': 193, 'function': '_debounced_sync', 'agent_name': '_debounced_sync', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                    try:
                        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=193)
                    except _gr_client.GuardrailUnavailableError:
                        pass
                    md.write_text(_lineaje_payload)
                t_last = time.time()
                w.step()
                time.sleep(2)
            deadline = time.time() + quiet * 3
            result = None
            while time.time() < deadline and result is None:
                result = w.step()
                time.sleep(0.25)
    finally:
        # LINEAJE: runtime guardrail checks `tmp` as it flows from the agent to system, at a security decision (in _debounced_sync).
        #   Detected: this statement moves data from the agent to system with no runtime policy check (detection confidence: medium).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_029; sensitive values in `tmp` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:b692f0e0dd83a05308b247082a031b85dff53cc8bd7de0efffcbff442e00be2e'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:b692f0e0dd83a05308b247082a031b85dff53cc8bd7de0efffcbff442e00be2e', phase='security_decision', boundary={'source': 'agent_message', 'sink': 'agent_message'}, fail_mode='BLOCK', source_type='agent', destination_type='system', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 204, 'function': '_debounced_sync'}, 'file': 'rag/eval/chunk_eval.py', 'line': 204, 'function': '_debounced_sync', 'agent_name': '_debounced_sync', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            tmp = _gr_client.enforce(_gr_site, tmp, content_type='application/json', variable_name='tmp', source_file=__file__, before_line=204)
        except _gr_client.GuardrailUnavailableError:
            pass
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
        _lineaje_payload = f"\nCode retrieval ({len(QUESTIONS)} questions over {len(CORPUS)} modules)"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:38be3fdee4dbbf2928706cdaf3332274f3334a77f3c46b89f0494d5eb701ff65'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:38be3fdee4dbbf2928706cdaf3332274f3334a77f3c46b89f0494d5eb701ff65', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 230, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 230, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        _lineaje_payload = f"  {'strategy':<28}{'chunks':>7}{'hit@1':>7}{'hit@3':>7}{'MRR':>7}{'whole fn':>9}{'dup text':>9}"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:e31d980ca2b6a6e7d71f0bb12caff9d21ecde6c50953c0872f7db0ce8c836526'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e31d980ca2b6a6e7d71f0bb12caff9d21ecde6c50953c0872f7db0ce8c836526', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 231, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 231, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for k, r in out["retrieval"].items():
            _lineaje_payload = (f"  {k:<28}{r['chunks']:>7}{r['hit@1']:>7.3f}{r['hit@3']:>7.3f}{r['mrr']:>7.3f}"
                  f"{r['complete@1']:>9.3f}{r['duplicated_text']:>9.3f}")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:5930b83c71a7f31133201b68393e454a031f68063625834af9d554bb415f58d9'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:5930b83c71a7f31133201b68393e454a031f68063625834af9d554bb415f58d9', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 233, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 233, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
        _lineaje_payload = ("  latency: " + "; ".join(
            f"{k.split(' ')[0]} chunk p50 {r['chunk_ms_per_file']['p50']} ms/file, "
            f"query p50 {r['query_ms']['p50']} ms" for k, r in out["retrieval"].items()))
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:7aa959f3797f87be42b983aa528aa7aacbc1cd0d40861a0c5d6c2bedc586b4e7'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:7aa959f3797f87be42b983aa528aa7aacbc1cd0d40861a0c5d6c2bedc586b4e7', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 235, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 235, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        _lineaje_payload = "\nEdit locality (chunks whose hash changes per edit)"
        # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
        #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:95a08f73f12302ab6f45714d0679750bd1325f583024c2ea8d1dc1dc3e651503'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:95a08f73f12302ab6f45714d0679750bd1325f583024c2ea8d1dc1dc3e651503', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 238, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 238, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
        try:
            _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
        print(_lineaje_payload)
        for k, r in out["edit_locality"].items():
            _lineaje_payload = (f"  {k:<28} edit inside a function: {r['edit_inside_function']:<5}  "
                  f"insert a function above: {r['insert_function_above']}  ({r['edits']} edits)")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:840b44e9e7c09cfb8beb11c66f5c2597c91fabfb1b3b98252d8392c597101b8f'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:840b44e9e7c09cfb8beb11c66f5c2597c91fabfb1b3b98252d8392c597101b8f', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 240, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 240, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
    if sync:
        out["debounce"] = _debounced_sync()
        if verbose:
            d = out["debounce"]
            _lineaje_payload = (f"\nDebounced sync ({d['debounce_seconds']:g} s): {d['saves']} saves -> {d['syncs']} sync, "
                  f"{d['wait_after_last_save_s']} s after the last save; {d['versions_built']} versions built "
                  f"(vs {d['versions_without_debounce']} without debounce)")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:94e9ed07d692361d0b22232c81b9804fd6d664e5d6f89b50a9a4e6ebd100b698'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:94e9ed07d692361d0b22232c81b9804fd6d664e5d6f89b50a9a4e6ebd100b698', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 246, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 246, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
            for f, x in d["diff"].items():
                _lineaje_payload = (f"  diff {f}: {x['total']} chunks, {x['unchanged']} unchanged, "
                      f"{x['added']} new/changed, {x['removed']} removed")
                # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
                #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
                #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
                #   Do not remove without review. site_id='site:sha256:4e30b12be847cf77fdaf3abc751de885bf30998bb267879a2630f8512d37ce55'
                _gr_client = _lineaje_load_gr_client()
                _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4e30b12be847cf77fdaf3abc751de885bf30998bb267879a2630f8512d37ce55', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 250, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 250, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
                try:
                    _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
                except _gr_client.GuardrailUnavailableError:
                    pass
                except PermissionError:
                    pass
                print(_lineaje_payload)
            _lineaje_payload = (f"  embedded {d['chunks_embedded']}, reused {d['chunks_reused']}; sync took "
                  f"{d['sync_ms']} ms; last save -> live in {d['change_to_live_s']} s")
            # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to the application log, before it is written to the log (in run_chunk_eval).
            #   Detected: this statement moves data from the agent to the application log with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_010; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:c01b7de1dbdde875c8c8bd49c4785e56ff61b830fe6cced84973b2efacee1131'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c01b7de1dbdde875c8c8bd49c4785e56ff61b830fe6cced84973b2efacee1131', phase='log_emit', boundary={'source': 'log', 'sink': 'log'}, fail_mode='BLOCK', source_type='agent', destination_type='log', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 252, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 252, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            print(_lineaje_payload)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    path = config.EVAL_RESULTS_DIR / f"chunking-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to an external endpoint, before it leaves the application (in run_chunk_eval).
    #   Detected: this statement moves data from the agent to an external endpoint with no runtime policy check (detection confidence: medium).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `out` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:fe914b80f5864044348bb9c3f34181f31623fa1c63b7a315c66b0d82af1d4943'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:fe914b80f5864044348bb9c3f34181f31623fa1c63b7a315c66b0d82af1d4943', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'external_endpoint'}, fail_mode='ALLOW_WITH_AUDIT', source_type='agent', destination_type='external', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 257, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 257, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='application/json', variable_name='out', source_file=__file__, before_line=257)
    except _gr_client.GuardrailUnavailableError:
        pass
    _lineaje_payload = json.dumps(out, indent=2, default=str)
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the agent to a file, before it is written to disk (in run_chunk_eval).
    #   Detected: this statement moves data from the agent to a file with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_025; sensitive values in `_lineaje_payload` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:e46cf7567f6b98776e073561d5517711b0bcde6acf76d753f86d8a804a19a0c6'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e46cf7567f6b98776e073561d5517711b0bcde6acf76d753f86d8a804a19a0c6', phase='file_write', boundary={'source': 'agent_message', 'sink': 'file_content'}, fail_mode='BLOCK', source_type='agent', destination_type='file', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 257, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 257, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=257)
    except _gr_client.GuardrailUnavailableError:
        pass
    path.write_text(_lineaje_payload)
    out["path"] = str(path)
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in run_chunk_eval).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:2e4a1e7e62c437991d67ef45e3431ce79920ade4df65505310d5391398b353da'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:2e4a1e7e62c437991d67ef45e3431ce79920ade4df65505310d5391398b353da', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/eval/chunk_eval.py', 'line': 259, 'function': 'run_chunk_eval'}, 'file': 'rag/eval/chunk_eval.py', 'line': 259, 'function': 'run_chunk_eval', 'agent_name': 'run_chunk_eval', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out
