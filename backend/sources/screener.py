"""Screener.in company page -> structured, primary-sourced fundamentals.

Screener consolidates exchange filings (quarterly results, annual P&L / balance
sheet / cash flow) and links to the primary documents (annual reports, concall
transcripts, exchange announcements). We only use the *numbers* and the *links*;
Screener's own commentary / AI summaries are deliberately ignored so the Pull side
stays grounded in primary data.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from ..util import http_get, cache_json

BASE = "https://www.screener.in"
_last_call = [0.0]


def _polite_get(url: str) -> str:
    # Be a good citizen: at most ~1 request / 1.5s to screener.
    wait = 1.5 - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    return http_get(url).text


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.replace(",", "").replace("%", "").replace("₹", "").replace("Cr.", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _label(td) -> str:
    t = td.get_text(" ", strip=True).replace("\xa0", " ")
    return re.sub(r"\s*\+\s*$", "", t).strip()


def _table(soup: BeautifulSoup, section_id: str) -> dict[str, Any] | None:
    sec = soup.find("section", id=section_id)
    if not sec:
        return None
    tbl = sec.find("table", class_="data-table")
    if not tbl:
        return None
    heads = [th.get_text(" ", strip=True) for th in tbl.find("thead").find_all("th")][1:]
    rows: dict[str, list[float | None]] = {}
    for tr in tbl.find("tbody").find_all("tr", recursive=False):
        tds = tr.find_all("td")
        if not tds or tr.has_attr("hidden"):
            continue
        lab = _label(tds[0])
        if not lab or lab.lower().startswith("raw pdf"):
            continue
        rows[lab] = [_num(td.get_text(strip=True)) for td in tds[1:]]
    return {"periods": heads, "rows": rows}


def _top_ratios(soup) -> dict[str, Any]:
    out = {}
    ul = soup.find("ul", id="top-ratios")
    if not ul:
        return out
    for li in ul.find_all("li"):
        name = li.find("span", class_="name")
        nums = li.find_all("span", class_="number")
        if not name:
            continue
        key = name.get_text(strip=True)
        vals = [_num(n.get_text()) for n in nums]
        out[key] = vals[0] if len(vals) == 1 else vals
    return out


def _documents(soup) -> dict[str, Any]:
    docs: dict[str, Any] = {"announcements": [], "annual_reports": [], "concalls": []}
    tab = soup.find(id="company-announcements-tab")
    if tab:
        docs["announcements"] = parse_announcements_html(str(tab))
    ar = soup.find("div", class_="annual-reports")
    if ar:
        for a in ar.find_all("a", href=True):
            txt = a.get_text(" ", strip=True)
            m = re.search(r"(20\d\d)", txt)
            if m and "annual report" in txt.lower():
                docs["annual_reports"].append({"year": int(m.group(1)), "url": a["href"], "label": txt})
    cc = soup.find("div", class_="concalls")
    if cc:
        for li in cc.find_all("li"):
            when = li.find("div")
            item = {"label": when.get_text(strip=True) if when else "", "transcript": None, "ppt": None}
            for a in li.find_all("a", href=True):
                t = (a.get("title") or a.get_text(strip=True)).lower()
                if "transcript" in t:
                    item["transcript"] = a["href"]
                elif t == "ppt":
                    item["ppt"] = a["href"]
            docs["concalls"].append(item)
    return docs


def parse_announcements_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        tm = li.find("time")
        sub = li.find("div", class_="smaller")
        title_txt = a.get_text("\n", strip=True).split("\n")[0].strip()
        snippet = ""
        if sub:
            snippet = sub.get_text(" ", strip=True)
            snippet = re.sub(r"^\d{1,2} \w{3}( \d{4})?\s*-\s*", "", snippet)
        out.append({
            "title": title_txt,
            "url": a["href"],
            "ts": tm["datetime"] if tm and tm.has_attr("datetime") else None,
            "hint": snippet,
        })
    return out


def fetch_company(symbol: str, max_age_h: float = 6) -> dict[str, Any]:
    """Parse the company page (consolidated, falling back to standalone)."""
    symbol = symbol.upper().strip()

    def _load():
        last_err = None
        for variant in ("consolidated/", ""):
            try:
                html = _polite_get(f"{BASE}/company/{symbol}/{variant}")
            except Exception as e:  # 404 etc
                last_err = e
                continue
            soup = BeautifulSoup(html, "lxml")
            q = _table(soup, "quarters")
            if not q or not q["rows"] or all(v is None for v in next(iter(q["rows"].values()))):
                continue
            info = soup.find(attrs={"data-company-id": True})
            name_el = soup.find("h1")
            about = soup.find("div", class_="about")
            bse = soup.find("a", href=re.compile(r"bseindia\.com/stock-share-price/"))
            bse_code = None
            if bse:
                m = re.search(r"/(\d{6})/?$", bse["href"].rstrip("/") + "/")
                m = m or re.search(r"/(\d{6})/", bse["href"])
                bse_code = m.group(1) if m else None
            pl = _table(soup, "profit-loss")
            return {
                "symbol": symbol,
                "name": name_el.get_text(" ", strip=True) if name_el else symbol,
                "company_id": info["data-company-id"] if info else None,
                "warehouse_id": info.get("data-warehouse-id") if info else None,
                "basis": "consolidated" if variant else "standalone",
                "about": re.sub(r"\[\d+\]", "", about.get_text(" ", strip=True)).strip() if about else "",
                "bse_code": bse_code,
                "ratios": _top_ratios(soup),
                "quarters": q,
                "pl": pl,
                "bs": _table(soup, "balance-sheet"),
                "cf": _table(soup, "cash-flow"),
                "eff": _table(soup, "ratios"),
                "is_financial": bool(q and any(k.startswith("Financing Profit") for k in q["rows"])),
                "docs": _documents(soup),
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
        raise ValueError(f"Screener has no data for '{symbol}' ({last_err or 'empty tables'})")

    return cache_json(f"screener/{symbol}", _load, max_age_h=max_age_h)


def fetch_recent_announcements(company_id: str) -> list[dict[str, Any]]:
    html = _polite_get(f"{BASE}/announcements/recent/{company_id}/")
    return parse_announcements_html(html)


def price_volume(company_id: str, days: int = 365) -> list[dict[str, Any]]:
    """Fallback EOD source (used if Yahoo rate-limits a datacenter IP)."""
    import json
    raw = json.loads(_polite_get(f"{BASE}/api/company/{company_id}/chart/?q=Price-Volume&days={days}"))
    series = {d["metric"]: d["values"] for d in raw.get("datasets", [])}
    vol = {v[0]: v[1] for v in series.get("Volume", [])}
    return [{"date": d, "close": float(p), "volume": float(vol.get(d) or 0)} for d, p in series.get("Price", [])]
