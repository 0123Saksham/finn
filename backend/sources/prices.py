"""End-of-day price & volume. Yahoo (one batched request for the whole book) with a
Screener chart-API fallback, because Yahoo often rate-limits datacenter IPs."""
from __future__ import annotations

import logging
from typing import Any

from ..util import cache_json, read_cache

log = logging.getLogger("finn.prices")


def _from_yahoo(symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    import yfinance as yf

    tick = [f"{s}.NS" for s in symbols]
    df = yf.download(tick, period="1y", interval="1d", group_by="ticker",
                     auto_adjust=False, progress=False, threads=True)
    out: dict[str, list[dict[str, Any]]] = {}
    for s, t in zip(symbols, tick):
        try:
            sub = df[t].dropna(subset=["Close"])
        except Exception:
            continue
        rows = [{"date": str(i.date()), "close": round(float(r["Close"]), 2), "volume": float(r["Volume"])}
                for i, r in sub.iterrows()]
        if len(rows) > 30:
            out[s] = rows
    return out


def history(symbols: list[str], max_age_h: float = 3) -> dict[str, list[dict[str, Any]]]:
    def _load():
        data = {}
        try:
            data = _from_yahoo(symbols)
        except Exception as e:  # noqa: BLE001
            log.warning("yahoo failed: %s", e)
        missing = [s for s in symbols if s not in data]
        if missing:
            from .screener import fetch_company, price_volume
            for s in missing:
                try:
                    cid = fetch_company(s)["company_id"]
                    data[s] = price_volume(cid)
                except Exception as e:  # noqa: BLE001
                    log.warning("screener price fallback failed for %s: %s", s, e)
        if not data:
            raise RuntimeError("no price source available")
        return data

    key = "prices/" + "_".join(sorted(symbols))[:120]
    return cache_json(key, _load, max_age_h=max_age_h)


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-stock EOD stats used by the alert engine and the UI."""
    if len(rows) < 2:
        return {}
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    last, prev = closes[-1], closes[-2]

    def ret(n):
        return round((closes[-1] / closes[-1 - n] - 1) * 100, 2) if len(closes) > n else None

    avg20 = sum(vols[-21:-1]) / max(1, len(vols[-21:-1]))
    return {
        "date": rows[-1]["date"],
        "close": last,
        "chg_pct": round((last / prev - 1) * 100, 2),
        "ret_5d": ret(5),
        "ret_1m": ret(21),
        "ret_3m": ret(63),
        "volume": vols[-1],
        "avg_vol_20": round(avg20),
        "vol_x": round(vols[-1] / avg20, 2) if avg20 else None,
        "hi_52w": max(closes[-252:]),
        "lo_52w": min(closes[-252:]),
        "spark": closes[-60:],
    }


def daily_events(rows: list[dict[str, Any]], days: int = 30) -> list[dict[str, Any]]:
    """For every day in the lookback: return %, volume multiple. Lets the rules screen
    preview how often a threshold *would have* fired — you see the noise you're opting into."""
    out = []
    for i in range(max(21, len(rows) - days), len(rows)):
        prev = rows[i - 1]["close"]
        avg20 = sum(r["volume"] for r in rows[i - 20:i]) / 20
        out.append({
            "date": rows[i]["date"],
            "close": rows[i]["close"],
            "chg_pct": round((rows[i]["close"] / prev - 1) * 100, 2),
            "vol_x": round(rows[i]["volume"] / avg20, 2) if avg20 else None,
        })
    return out
