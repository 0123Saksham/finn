"""Primary documents: download once, extract text page-by-page, cache forever.
A filing URL never changes content, so the cache key is the URL itself."""
from __future__ import annotations

import re
from typing import Any

import fitz  # PyMuPDF

from ..util import CACHE, h, http_get, read_cache, write_cache

PDF_DIR = CACHE / "pdf"
PDF_DIR.mkdir(parents=True, exist_ok=True)


def pdf_bytes(url: str, max_mb: float = 40) -> bytes:
    p = PDF_DIR / f"{h(url)}.pdf"
    if p.exists():
        return p.read_bytes()
    r = http_get(url)
    data = r.content
    if not data[:5].startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {url}")
    if len(data) > max_mb * 1e6:
        raise ValueError("pdf too large")
    # Only keep small PDFs on disk (filings); big annual reports are re-derivable from text cache.
    if len(data) < 3e6:
        p.write_bytes(data)
    return data


def pdf_pages(url: str) -> list[str]:
    key = f"text/{h(url)}"
    hit = read_cache(key)
    if hit is not None:
        return hit
    data = pdf_bytes(url)
    doc = fitz.open(stream=data, filetype="pdf")
    pages = [re.sub(r"[ \t]+", " ", pg.get_text("text")).strip() for pg in doc]
    write_cache(key, pages)
    return pages


def page_count(url: str) -> int:
    try:
        return len(pdf_pages(url))
    except Exception:
        return 0


def is_scanned(pages: list[str]) -> bool:
    chars = sum(len(p) for p in pages[:5])
    return chars < 200 * max(1, min(5, len(pages)))


def select_pages(pages: list[str], keywords: dict[str, float], budget_chars: int,
                 must: list[int] | None = None) -> list[tuple[int, str]]:
    """Cheap retrieval: score every page by weighted keyword hits, keep the best pages
    within a character budget, return them in document order. This is how a 300-page
    annual report becomes ~15 pages of input for the model."""
    scored = []
    for i, txt in enumerate(pages):
        low = txt.lower()
        s = sum(w * low.count(k) for k, w in keywords.items())
        if len(txt) < 300:
            s *= 0.2
        scored.append((s, i))
    scored.sort(reverse=True)
    keep: set[int] = set(must or [])
    used = sum(len(pages[i]) for i in keep)
    for s, i in scored:
        if s <= 0 or used > budget_chars:
            break
        if i not in keep:
            keep.add(i)
            used += len(pages[i])
    return [(i + 1, pages[i]) for i in sorted(keep)]


def first_text(url: str, chars: int = 2500) -> str:
    try:
        pages = pdf_pages(url)
    except Exception:
        return ""
    return "\n".join(pages)[:chars]


def doc_meta(url: str) -> dict[str, Any]:
    pages = pdf_pages(url)
    return {"pages": len(pages), "scanned": is_scanned(pages)}
