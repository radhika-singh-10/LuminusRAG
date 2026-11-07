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
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import config
from .safety import looks_like_injection, redact_pii, strip_redactions
from .store import get_embeddings, get_vectorstore

USER_AGENT = "Mozilla/5.0 (compatible; rag-langchain/1.0)"
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
    if looks_like_injection(text):
        return None
    return redact_pii(text)[0]


def web_documents(query: str, k: int | None = None) -> tuple[list[Document], dict]:
    """Search, fetch, clean and rank. Returns (top-k passages, stats).

    `query` must already be PII-redacted: it is sent to the search engine.
    """
    k = k or config.TOP_K
    stats = {"results": 0, "pages_fetched": 0, "passages": 0, "dropped_injection": 0}
    results = web_search(strip_redactions(query))
    stats["results"] = len(results)
    if not results:
        return [], stats

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
    )
    candidates: list[Document] = []
    for i, r in enumerate(results):
        meta = {"source": r["href"], "title": r.get("title", "")[:200], "origin": "web"}
        text = fetch_text(r["href"]) if i < config.WEB_FETCH_PAGES else None
        pieces = splitter.split_text(text)[:MAX_CHUNKS_PER_PAGE] if text else []
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

    emb = get_embeddings()
    q = np.asarray(emb.embed_query(query))
    d = np.asarray(emb.embed_documents([c.page_content for c in candidates]))
    picked = []
    for i in np.argsort(-(d @ q))[:k]:
        doc = candidates[i]
        doc.metadata["score"] = float(d[i] @ q)
        picked.append(doc)
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
    get_vectorstore().add_documents(to_store, ids=ids)
    return len(to_store)
