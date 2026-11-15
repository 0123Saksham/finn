"""NSE's official public RSS feed of corporate announcements (latest ~100, market-wide).
Polled on a schedule and accumulated, so FINN sees filings minutes after they land
without scraping NSE's private JSON APIs."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

from ..util import http_get

FEEDS = [
    "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
    "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
]


def norm_name(s: str) -> str:
    s = s.lower().replace("&", "and")
    s = re.sub(r"\b(limited|ltd\.?|the|india|\(india\)|co\.?|company|enterprise|industries)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def fetch() -> list[dict[str, Any]]:
    items = []
    for url in FEEDS:
        try:
            root = ET.fromstring(http_get(url).content)
        except Exception:
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = (it.findtext("description") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            try:
                ts = datetime.strptime(pub, "%d-%b-%Y %H:%M:%S").isoformat() + "+05:30"
            except ValueError:
                ts = None
            subject = desc.split("|SUBJECT:")[-1].strip() if "|SUBJECT:" in desc else desc
            m = re.match(r".*/corporate/([A-Z0-9&\-]+)_\d{8,}", link)
            items.append({
                "company": title, "sym_hint": m.group(1) if m else None,
                "title": subject, "url": link, "ts": ts, "hint": "", "source": "NSE RSS",
            })
    return items


def match(items: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
    """names: normalised company name -> symbol."""
    out = []
    for it in items:
        sym = None
        if it["sym_hint"] and it["sym_hint"] in names.values():
            sym = it["sym_hint"]
        else:
            sym = names.get(norm_name(it["company"]))
        if sym:
            out.append({**it, "symbol": sym})
    return out
