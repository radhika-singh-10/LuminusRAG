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
    return out
