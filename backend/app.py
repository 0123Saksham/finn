"""FINN API + static PWA. One process, one container."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import timedelta
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, llm
from .pull import numbers, research
from .push import feed
from .sources import screener
from .util import ROOT, http_get

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("finn")
app = FastAPI(title="FINN")
app.add_middleware(GZipMiddleware, minimum_size=800)


def _rules(price_move_pct, volume_multiple, categories):
    r = dict(config.DEFAULT_RULES)
    if price_move_pct is not None:
        r["price_move_pct"] = price_move_pct
    if volume_multiple is not None:
        r["volume_multiple"] = volume_multiple
    if categories is not None:
        r["categories"] = [c for c in categories.split(",") if c]
    return r


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.available(), "models": llm.MODELS, "feed": {k: v for k, v in feed.STATUS.items() if k != "log"}}


@app.get("/api/digest")
def digest(hours: float = 24, since: str | None = None, price_move_pct: float | None = None,
           volume_multiple: float | None = None, categories: str | None = None, muted: str | None = None):
    return feed.digest(hours=hours, since=since, rules=_rules(price_move_pct, volume_multiple, categories),
                       muted=[m for m in (muted or "").split(",") if m])


@app.get("/api/rules/preview")
def rules_preview(price_move_pct: float | None = None, volume_multiple: float | None = None,
                  categories: str | None = None, days: int = 30):
    return feed.rules_preview(_rules(price_move_pct, volume_multiple, categories), lookback_days=days)


@app.get("/api/portfolio")
def portfolio():
    px = feed.price_stats()
    store = feed.load_store()
    cut = (feed.now() - timedelta(days=7)).isoformat()
    out = []
    for p in config.PORTFOLIO:
        s = p["symbol"]
        try:
            c = screener.fetch_company(s, max_age_h=48, swr=True)
            name, mcap = c["name"], c["ratios"].get("Market Cap")
        except Exception:  # noqa: BLE001
            name, mcap = s, None
        items = [it for it in store.values() if it["symbol"] == s and (it.get("ts") or "") >= cut]
        top = max(items, key=lambda x: x.get("materiality", 0), default=None)
        out.append({**p, "name": name, "mcap_cr": mcap, "px": px.get(s, {}),
                    "filings_7d": len(items),
                    "material_7d": sum(1 for x in items if x.get("materiality", 0) >= feed.TIER_MATTERS),
                    "top": {"title": (top.get("enrich") or {}).get("line") or (top.get("enrich") or {}).get("headline") or top["title"],
                            "label": feed.LABEL.get(top.get("category")), "materiality": top.get("materiality")} if top else None})
    return {"holdings": out, "as_of": next(iter(px.values()), {}).get("date") if px else None}


@app.get("/api/company/{symbol}")
def company(symbol: str):
    s = symbol.upper()
    try:
        c = screener.fetch_company(s, max_age_h=24, swr=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"No data for {s}: {e}")
    store = feed.load_store()
    items = sorted([it for it in store.values() if it["symbol"] == s], key=lambda x: x.get("ts") or "", reverse=True)
    px = feed.price_stats().get(s)
    if not px:
        try:
            from .sources import prices
            rows = prices.history([s], max_age_h=6, swr=True).get(s, [])
            px = prices.stats(rows) if rows else None
        except Exception:  # noqa: BLE001
            px = None
    nums = numbers.analyse(c)
    return {"symbol": s, "name": c["name"], "about": c.get("about"), "in_portfolio": s in config.WEIGHT,
            "weight": config.WEIGHT.get(s), "sector": config.SECTOR.get(s), "px": px,
            "snapshot": nums["snapshot"], "quarters": nums["quarters"][-5:],
            "filings": [{"title": it["title"], "url": it["url"], "ts": it.get("ts"), "label": feed.LABEL.get(it.get("category")),
                         "materiality": it.get("materiality"), "enrich": it.get("enrich")} for it in items[:25]],
            "research": research.status(s) is not None}


@app.post("/api/research/{symbol}")
def research_start(symbol: str, force: bool = False):
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,20}", symbol):
        raise HTTPException(400, "bad symbol")
    return research.run(symbol, force=force)


@app.get("/api/research/{symbol}")
def research_status(symbol: str):
    st = research.status(symbol)
    if not st:
        raise HTTPException(404, "not started")
    return st


@app.post("/api/ask")
def ask(payload: dict = Body(...)):
    sym, q = str(payload.get("symbol", "")), str(payload.get("question", ""))[:400]
    if not sym or not q:
        raise HTTPException(400, "symbol and question required")
    try:
        return research.ask(sym, q)
    except llm.LLMUnavailable as e:
        return {"answer": f"Model unavailable: {e}", "confidence": "low", "sources": []}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=40)):
    try:
        from urllib.parse import quote
        r = http_get(f"https://www.screener.in/api/company/search/?q={quote(q)}&v=3&fts=1").json()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for x in r[:8]:
        m = re.search(r"/company/([^/]+)/", x.get("url", ""))
        if m and not m.group(1).isdigit() and m.group(1) != "id":
            out.append({"symbol": m.group(1), "name": x["name"]})
    return out


@app.post("/api/command")
def command(payload: dict = Body(...)):
    from .command import route
    text = str(payload.get("text", "")).strip()[:300]
    if not text:
        raise HTTPException(400, "text required")
    return route(text)


@app.get("/api/ledger")
def ledger():
    return {"session": llm.LEDGER, "models": llm.MODELS, "last_refresh_cost": feed.STATUS.get("last_cost")}


@app.post("/api/refresh")
def refresh():
    if not feed.STATUS["running"]:
        threading.Thread(target=feed.refresh, daemon=True).start()
    return {"started": True}


@app.get("/api/demo")
def demo():
    return {"research": config.RESEARCH_DEMO, "portfolio": config.SYMBOLS}


# ----------------------------------------------------------------------------- scheduler

def _scheduler():
    # Let the first page load finish before the refresh competes for a small CPU.
    time.sleep(20)
    while True:
        try:
            feed.refresh()
        except Exception:  # noqa: BLE001
            log.exception("scheduled refresh failed")
        # Every 20 min while companies file; hourly nights and weekends.
        time.sleep((config.REFRESH_MINUTES if feed.active_window() else 60) * 60)


def _keepalive(url: str):
    """Free hosts sleep after ~15 idle minutes, and waking takes close to a minute. A light
    self-ping through the public URL keeps the brief instant for whoever opens it next."""
    import httpx
    while True:
        time.sleep(10 * 60)
        try:
            httpx.get(url.rstrip("/") + "/api/health", timeout=20)
        except Exception:  # noqa: BLE001
            pass


@app.on_event("startup")
def _start():
    import os
    if os.getenv("FINN_NO_SCHEDULER") != "1":
        threading.Thread(target=_scheduler, daemon=True, name="scheduler").start()
    url = os.getenv("FINN_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if os.getenv("FINN_KEEPALIVE") == "1" and url:
        threading.Thread(target=_keepalive, args=(url,), daemon=True, name="keepalive").start()


# ----------------------------------------------------------------------------- static PWA

DIST = ROOT / "frontend" / "dist"


class _Immutable(StaticFiles):
    """Vite fingerprints asset filenames, so they can be cached for a year with no revalidation."""
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        if r.status_code == 200:
            r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return r


if DIST.exists():
    app.mount("/assets", _Immutable(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "unknown endpoint")
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f, headers={"Cache-Control": "no-cache"} if path == "sw.js" else None)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
