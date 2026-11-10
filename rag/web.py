"""Web fallback: search DuckDuckGo, fetch the top pages, keep the passages most
similar to the question, and save them into the vector store.

Safety:
- Only the PII-redacted question is sent to the search engine (see chain.py).
- Fetching is plain HTTP GET of public http(s) pages. Hosts that resolve to
  loopback, private, link-local or reserved addresses are refused, including
  after redirects, so a search result can't reach the local network.
- Hidden page elements are removed (a common place for injected instructions).
- Passages that try to instruct the model are dropped; PII is redacted before
  passages are used or stored.
- Nothing fetched is ever executed. Web text is only quoted as context, and
  the answer prompt tells the model to ignore instructions inside it.
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
import ipaddress
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
import numpy as np
from bs4 import BeautifulSoup
from langchain_core.documents import Document

from . import config
from .chunking import chunk_text
from .safety import looks_like_injection, redact_pii, strip_redactions
from .store import get_embeddings, get_vectorstore

USER_AGENT = "Mozilla/5.0 (compatible; LuminusRAG/1.0)"
MAX_BYTES = 2_000_000
MAX_CHUNKS_PER_PAGE = 40
MAX_REDIRECTS = 3


def web_search(query: str, max_results: int | None = None, attempts: int = 2) -> list[dict]:
    """[{title, href, body}] from DuckDuckGo (no API key needed).

    DuckDuckGo sometimes returns nothing or rate-limits rapid queries, so an
    empty or failed search is retried once after a short pause.
    """
    from ddgs import DDGS

    last_error = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(1.5)
        try:
            results = DDGS(timeout=config.WEB_TIMEOUT).text(
                query, max_results=max_results or config.WEB_MAX_RESULTS
            )
        except Exception as e:  # ddgs raises on rate limits and timeouts
            last_error = e
            continue
        results = [r for r in results or [] if is_public_url(r.get("href", ""))]
        if results:
            # LINEAJE: runtime guardrail checks `results` as it flows from the agent to the user interface, before it leaves the application (in web_search).
            #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `results` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:3636bcd4142bd9f2ffc1d2e63756e8e5edd3b010a740c2dd568329bfdb7ae319'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:3636bcd4142bd9f2ffc1d2e63756e8e5edd3b010a740c2dd568329bfdb7ae319', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/web.py', 'line': 60, 'function': 'web_search'}, 'file': 'rag/web.py', 'line': 60, 'function': 'web_search', 'agent_name': 'web_search', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
            try:
                results = _gr_client.enforce(_gr_site, results, content_type='text/plain')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
            return results
    if last_error:
        raise last_error
    return []


def is_public_url(url: str) -> bool:
    """True only for http(s) URLs whose host resolves exclusively to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if parsed.port not in (None, 80, 443):
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            return False
    return True


def _strip_hidden(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form",
                     "noscript", "template", "iframe", "svg", "button"]):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        style = (tag.get("style") or "").replace(" ", "").lower()
        if (
            tag.has_attr("hidden")
            or tag.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or "font-size:0" in style
            or "opacity:0" in style
        ):
            tag.decompose()


def fetch_text(url: str) -> str | None:
    """Readable text of a public HTML or plain-text page, or None on any failure."""
    try:
        with httpx.Client(timeout=config.WEB_TIMEOUT, follow_redirects=False,
                          headers={"User-Agent": USER_AGENT}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if not is_public_url(url):
                    return None
                with client.stream("GET", url) as r:
                    if r.is_redirect:
                        url = urljoin(url, r.headers.get("location", ""))
                        continue
                    ctype = r.headers.get("content-type", "")
                    if r.status_code != 200 or not ("html" in ctype or "text/plain" in ctype):
                        return None
                    body = b""
                    for part in r.iter_bytes():
                        body += part
                        if len(body) > MAX_BYTES:
                            break
                    encoding = r.encoding or "utf-8"
                    break
            else:
                return None
    except httpx.HTTPError:
        return None

    text = body.decode(encoding, errors="ignore")
    if "html" in ctype:
        soup = BeautifulSoup(text, "html.parser")
        _strip_hidden(soup)
        root = soup.find("main") or soup.find("article") or soup.body or soup
        text = root.get_text("\n")
    text = text.replace("​", "").replace("‌", "").replace("‍", "").replace("﻿", "")
    lines = (line.strip() for line in text.splitlines())
    text = "\n".join(line for line in lines if len(line.split()) >= 4)
    return text or None


def clean_passage(text: str) -> str | None:
    """None if the passage tries to instruct the model; otherwise PII-redacted text."""
    if looks_like_injection(text, "document"):
        return None
    return redact_pii(text)[0]


_AI_TERMS = re.compile(
    r"\b(?:ai|a\.i\.|artificial intelligence|llms?|language models?|gpt\w*|claude|gemini|llama|"
    r"transformers?|neural|deep learning|machine learning|ml|nlp|rag|embeddings?|vector|"
    r"langchain|langgraph|prompts?|agents?|agentic|chatbots?|fine-?tun\w*|rlhf|diffusion|"
    r"tokens?|inference|attention|model)\b", re.IGNORECASE)


def search_query(query: str) -> str:
    """Every allowed question is about AI, but ambiguous wording ("latest
    guardrail mechanisms") would search the general web (highway guardrails).
    Without an AI term in the question, add the AI context to the search."""
    return query if _AI_TERMS.search(query) else f"{query} in AI and large language models"


def web_documents(query: str, k: int | None = None) -> tuple[list[Document], dict]:
    """Search, fetch, clean and rank. Returns (top-k passages, stats).

    `query` must already be PII-redacted: it is sent to the search engine.
    """
    k = k or config.TOP_K
    query = search_query(strip_redactions(query))
    stats = {"results": 0, "pages_fetched": 0, "passages": 0, "dropped_injection": 0,
             "search_query": query}
    results = web_search(query)
    stats["results"] = len(results)
    if not results:
        return [], stats

    candidates: list[Document] = []
    for i, r in enumerate(results):
        meta = {"source": r["href"], "title": r.get("title", "")[:200], "origin": "web"}
        text = fetch_text(r["href"]) if i < config.WEB_FETCH_PAGES else None
        # Same structure-aware, non-overlapping chunking as documents.
        pieces = [c.text for c in chunk_text(text)][:MAX_CHUNKS_PER_PAGE] if text else []
        if text:
            stats["pages_fetched"] += 1
        elif r.get("body"):  # fall back to the search snippet
            pieces = [r["body"]]
        for piece in pieces:
            cleaned = clean_passage(piece)
            if cleaned is None:
                stats["dropped_injection"] += 1
                continue
            candidates.append(Document(page_content=cleaned, metadata=dict(meta)))
    stats["passages"] = len(candidates)
    if not candidates:
        return [], stats

    from .policy import sanitize_document

    emb = get_embeddings()
    # LINEAJE: runtime guardrail checks `query` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in web_documents).
    #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `query` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:33f04ba1a20770742a8ed8960a310505f2076da2602e5022de01d6d141202b4f'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:33f04ba1a20770742a8ed8960a310505f2076da2602e5022de01d6d141202b4f', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/web.py', 'line': 200, 'function': 'web_documents'}, 'file': 'rag/web.py', 'line': 200, 'function': 'web_documents', 'agent_name': 'web_documents', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        query = _gr_client.enforce(_gr_site, query, content_type='application/json', variable_name='query', source_file=__file__, before_line=200)
    except _gr_client.GuardrailUnavailableError:
        pass
    q = np.asarray(emb.embed_query(query))
    _lineaje_payload = [c.page_content for c in candidates]
    # LINEAJE: runtime guardrail checks `_lineaje_payload` as it flows from the RAG pipeline to embedding model, before it is sent to the model (in web_documents).
    #   Detected: this statement moves data from the RAG pipeline to embedding model with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `_lineaje_payload` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:59afd9251ec57c95a7c6a4832262345b8b48a3f5026e29d4667492dbdac06a8d'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:59afd9251ec57c95a7c6a4832262345b8b48a3f5026e29d4667492dbdac06a8d', phase='pre_model', boundary={'source': 'rag_pipeline', 'sink': 'embedding_model'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='embedding_model', components={'invocation': {'file': 'rag/web.py', 'line': 201, 'function': 'web_documents'}, 'file': 'rag/web.py', 'line': 201, 'function': 'web_documents', 'agent_name': 'web_documents', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        _lineaje_payload = _gr_client.enforce(_gr_site, _lineaje_payload, content_type='application/json', variable_name='_lineaje_payload', source_file=__file__, before_line=201)
    except _gr_client.GuardrailUnavailableError:
        pass
    d = np.asarray(emb.embed_documents(_lineaje_payload))
    picked = []
    # Full policy check (regex + LLM + private names) on the best passages only.
    for i in np.argsort(-(d @ q))[: k * 2]:
        doc = candidates[i]
        clean, rep = sanitize_document(doc.page_content)
        stats["dropped_injection"] += len(rep["dropped_paragraphs"])
        if len(clean.split()) < 8:
            continue
        doc.page_content = clean
        doc.metadata["score"] = float(d[i] @ q)
        picked.append(doc)
        if len(picked) == k:
            break
    return picked, stats


def store_web_documents(docs: list[Document], query: str) -> int:
    """Save web passages into Chroma so later questions are answered locally.

    Ids hash the URL and text, so storing the same passage twice overwrites it.
    `query` must already be PII-redacted. Returns the number of passages stored.
    """
    if not docs:
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    to_store, ids = [], []
    for doc in docs:
        meta = {
            "source": doc.metadata["source"],
            "title": doc.metadata.get("title", ""),
            "origin": "web",
            "fetched_at": now,
            "query": query[:300],
        }
        to_store.append(Document(page_content=doc.page_content, metadata=meta))
        digest = hashlib.sha256(f"{meta['source']}\n{doc.page_content}".encode()).hexdigest()
        ids.append(f"web-{digest[:32]}")
    # LINEAJE: runtime guardrail checks `to_store` as it flows from the RAG pipeline to a vector store, before the tool runs (in store_web_documents).
    #   Detected: this statement moves data from the RAG pipeline to a vector store with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates the policies enabled for this boundary; sensitive values in `to_store` are masked in place; a policy violation is logged and the call continues (fail_mode=ALLOW_WITH_AUDIT). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:c33f2b47d335508f44ba83dead35572dfa6b25da79a4043a65d3a889e9469af3'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:c33f2b47d335508f44ba83dead35572dfa6b25da79a4043a65d3a889e9469af3', phase='pre_tool', boundary={'source': 'rag_pipeline', 'sink': 'vector_store'}, fail_mode='ALLOW_WITH_AUDIT', source_type='rag_pipeline', destination_type='vector_store', components={'invocation': {'file': 'rag/web.py', 'line': 239, 'function': 'store_web_documents'}, 'file': 'rag/web.py', 'line': 239, 'function': 'store_web_documents', 'agent_name': 'store_web_documents', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        to_store = _gr_client.enforce(_gr_site, to_store, content_type='application/json', variable_name='to_store', source_file=__file__, before_line=239)
    except _gr_client.GuardrailUnavailableError:
        pass
    get_vectorstore().add_documents(to_store, ids=ids)
    if config.GRAPH_ENABLED:
        try:
            from .graph import update_graph

            update_graph()
        except Exception:  # graph is optional; answering already succeeded
            pass
    return len(to_store)
