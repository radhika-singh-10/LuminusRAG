"""OCR for scanned PDFs.

PDF pages whose text layer is empty (or nearly so, below OCR_MIN_CHARS) are
rendered with pypdfium2 at OCR_DPI and read with RapidOCR (PP-OCR models on
onnxruntime, local, bundled with the package: no network, no system install).

The recognised lines are put back in reading order: boxes are grouped into
rows by vertical position, each row is read left to right, and a vertical gap
of about a blank line (rows > 2.2 line heights apart) starts a new paragraph. Paragraph breaks matter
because the structure-aware chunker packs paragraphs (rag/chunking.py).
Lines below OCR_MIN_CONFIDENCE are dropped.

OCR text is untrusted like any document text: ingestion runs it through the
same policy sanitizer (prompt injection removed, PII redacted) afterwards,
so instructions hidden in an image are treated exactly like typed ones.

Limitations: single-column reading order (multi-column pages are read row by
row across columns), no heading detection, no handwriting.
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

import logging
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import config


@dataclass
class OcrPage:
    text: str
    confidence: float | None  # mean line confidence, None if nothing was read
    lines: int
    seconds: float


def needs_ocr(text: str) -> bool:
    return len("".join(text.split())) < config.OCR_MIN_CHARS


@lru_cache(maxsize=1)
def _engine():
    from rapidocr import RapidOCR

    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    # The 180-degree text-direction classifier flips some upright lines and
    # turns them into fragments ("en ig i s es"); scanned pages are upright,
    # and skew is handled by the detector, so it is off.
    return RapidOCR(params={"Global.use_cls": False})


def layout_text(boxes, txts, scores, min_conf: float | None = None) -> tuple[str, list[float]]:
    """OCR boxes -> text in reading order with paragraph breaks. Returns (text, kept scores)."""
    min_conf = config.OCR_MIN_CONFIDENCE if min_conf is None else min_conf
    items = []
    for box, txt, score in zip(boxes, txts, scores):
        if not txt.strip() or score < min_conf:
            continue
        b = np.asarray(box)
        y0, y1 = b[:, 1].min(), b[:, 1].max()
        items.append({"x": b[:, 0].min(), "y": (y0 + y1) / 2, "h": y1 - y0, "t": txt.strip(), "s": score})
    if not items:
        return "", []
    h = statistics.median(i["h"] for i in items) or 1.0
    rows: list[list[dict]] = []
    for it in sorted(items, key=lambda i: i["y"]):
        if rows and abs(it["y"] - statistics.fmean(r["y"] for r in rows[-1])) < 0.5 * h:
            rows[-1].append(it)
        else:
            rows.append([it])
    out, prev_y = [], None
    for row in rows:
        y = statistics.fmean(r["y"] for r in row)
        if prev_y is not None and y - prev_y > 2.2 * h:  # blank space: new paragraph
            out.append("")
        out.append(" ".join(r["t"] for r in sorted(row, key=lambda r: r["x"])))
        prev_y = y
    text = "\n".join(out)
    # Join hyphenated line breaks ("retrie-\nval" -> "retrieval").
    text = text.replace("-\n", "")
    return text, [i["s"] for i in items]


def ocr_image(image) -> OcrPage:
    """OCR one image (PIL image, numpy array or path)."""
    import time

    t0 = time.perf_counter()
    if not isinstance(image, (str, Path, np.ndarray)):
        image = np.asarray(image.convert("RGB"))
    r = _engine()(image)
    if r.boxes is None or not r.txts:
        return OcrPage("", None, 0, time.perf_counter() - t0)
    text, kept = layout_text(r.boxes, r.txts, r.scores)
    return OcrPage(text, round(statistics.fmean(kept), 4) if kept else None, len(kept),
                   time.perf_counter() - t0)


def ocr_pdf_pages(path: str | Path, pages: list[int], progress=None) -> dict[int, OcrPage]:
    """OCR the given 0-based pages of a PDF. progress(done, total) after each page."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    out = {}
    try:
        pages = [p for p in pages if 0 <= p < len(pdf)][: config.OCR_MAX_PAGES]
        for n, i in enumerate(pages, 1):
            page = pdf[i]
            try:
                image = page.render(scale=config.OCR_DPI / 72).to_pil()
            finally:
                page.close()
            out[i] = ocr_image(image)
            if progress:
                progress(n, len(pages))
    finally:
        pdf.close()
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in ocr_pdf_pages).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:e012e77292a6bcb0a70a9b6c4804d01ff336b0408416d82ac3d7b6261ad2a627'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:e012e77292a6bcb0a70a9b6c4804d01ff336b0408416d82ac3d7b6261ad2a627', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/ocr.py', 'line': 120, 'function': 'ocr_pdf_pages'}, 'file': 'rag/ocr.py', 'line': 120, 'function': 'ocr_pdf_pages', 'agent_name': 'ocr_pdf_pages', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return out
