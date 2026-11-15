"""Push side: ingest -> classify -> enrich -> cluster -> score -> digest / alerts."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, llm
from ..sources import nse_rss, prices, screener
from ..util import read_cache, write_cache
from . import classify, enrich

log = logging.getLogger("finn.feed")
IST = timezone(timedelta(hours=5, minutes=30))
STORE_KEY = "store/announcements"
_lock = threading.Lock()
STATUS: dict[str, Any] = {"last_refresh": None, "running": False, "log": []}

TIER_MATTERS, TIER_GLANCE = 70, 38
LABEL = {"results": "Results", "M&A": "M&A", "fund_raise": "Fund raise", "management_change": "People",
         "litigation": "Legal / regulatory", "insider_trading": "Insider deal", "earnings_call": "Earnings call",
         "investor_meetings": "Investor meet", "credit_rating": "Credit rating", "dividend": "Dividend",
         "bonus_split": "Bonus / split", "capex": "Capex", "press_release": "Update", "postal_ballot": "Postal ballot",
         "agm_egm": "AGM / EGM", "pledging": "Pledge", "unclassified": "Routine"}


def now() -> datetime:
    return datetime.now(IST)


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except ValueError:
        return None


def load_store() -> dict[str, dict]:
    return read_cache(STORE_KEY) or {}


def save_store(store: dict[str, dict]) -> None:
    write_cache(STORE_KEY, store)


def companies(max_age_h: float = 12) -> dict[str, dict]:
    out = {}
    for s in config.SYMBOLS:
        try:
            out[s] = screener.fetch_company(s, max_age_h=max_age_h)
        except Exception as e:  # noqa: BLE001
            log.warning("company %s: %s", s, e)
    return out


def _log(msg: str):
    STATUS["log"] = (STATUS["log"] + [f"{now():%H:%M:%S} {msg}"])[-40:]
    log.info(msg)


def refresh(enrich_days: int = 21, live: bool = True) -> dict[str, Any]:
    """Pull new filings, classify, enrich only what's material. Idempotent and cheap to re-run."""
    if STATUS["running"]:
        return STATUS
    STATUS["running"] = True
    meter: list = []
    try:
        comps = companies(max_age_h=12)
        store = load_store()
        before = len(store)
        fresh: list[dict] = []
        for s, c in comps.items():
            anns = c["docs"]["announcements"]
            if live and c.get("company_id"):
                try:
                    anns = screener.fetch_recent_announcements(c["company_id"]) or anns
                except Exception as e:  # noqa: BLE001
                    _log(f"{s}: screener recent failed ({e})")
            for a in anns:
                fresh.append({**a, "symbol": s, "source": "BSE via Screener"})
        if live:
            names = {nse_rss.norm_name(c["name"]): s for s, c in comps.items()}
            try:
                fresh += nse_rss.match(nse_rss.fetch(), names)
            except Exception as e:  # noqa: BLE001
                _log(f"NSE RSS failed ({e})")
        new_items = []
        for a in fresh:
            if a["url"] in store:
                continue
            item = {**a, "name": comps.get(a["symbol"], {}).get("name", a["symbol"]),
                    "first_seen": now().isoformat(timespec="seconds")}
            store[a["url"]] = item
            new_items.append(item)
        if llm.available():  # filings that arrived while no model was configured get a second look
            for it in store.values():
                if it.get("classified_by") == "default":
                    for k in ("category", "subtype", "materiality", "classified_by", "enrich"):
                        it.pop(k, None)
                    new_items.append(it)
        classify.classify_all(new_items, meter=meter)
        _log(f"ingested {len(new_items)} new filings ({len(store)} total, was {before})")

        cutoff = now() - timedelta(days=enrich_days)
        todo = [it for it in store.values()
                if "enrich" not in it and (_ts(it.get("ts")) or now()) >= cutoff
                and it.get("materiality", 0) >= 30 and llm.available()]

        def _work(it):
            e = enrich.enrich(it, comps.get(it["symbol"]), meter)
            it["enrich"] = e
            it["materiality"] = enrich.adjust_materiality(it)
            return it

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_work, todo))
        _log(f"enriched {len(todo)} material filings; LLM: {llm.summarize_meter(meter)}")
        with _lock:
            save_store(store)
        STATUS["last_refresh"] = now().isoformat(timespec="seconds")
        STATUS["last_cost"] = llm.summarize_meter(meter)
    finally:
        STATUS["running"] = False
    return STATUS


# ----------------------------------------------------------------------------- digest

def _family(it: dict) -> str:
    c = it.get("category")
    if c in ("results", "earnings_call"):
        return "results"
    return c or "other"


def _people(it: dict) -> set[str]:
    e = it.get("enrich") or {}
    return {" ".join((c.get("person") or "").replace(".", " ").split()[-2:]).lower() for c in e.get("changes", []) if c.get("person")}


def _same_event(a: dict, b: dict) -> bool:
    if a.get("category") == "management_change" and b.get("category") == "management_change":
        return a["title"] == b["title"] or bool(_people(a) & _people(b))
    if a.get("category") in ("M&A", "litigation") or b.get("category") in ("M&A", "litigation"):
        return a["title"] == b["title"]
    return True


def cluster(items: list[dict]) -> list[dict]:
    """Group filings about the same event (e.g. results + outcome + deck + ad) into one story."""
    items = sorted(items, key=lambda x: x.get("ts") or "", reverse=True)
    stories: list[dict] = []
    for it in items:
        t = _ts(it.get("ts")) or now()
        home = None
        for s in stories:
            if s["symbol"] == it["symbol"] and s["family"] == _family(it) and abs((s["_t"] - t).total_seconds()) < 3 * 86400 \
                    and _same_event(s["lead"], it):
                home = s
                break
        if home:
            home["filings"].append(it)
            if it.get("materiality", 0) > home["lead"].get("materiality", 0):
                home["lead"] = it
        else:
            stories.append({"symbol": it["symbol"], "family": _family(it), "_t": t, "lead": it, "filings": [it]})
    return stories


def score_story(s: dict, px: dict[str, dict], rules: dict) -> float:
    lead = s["lead"]
    m = max(f.get("materiality", 0) for f in s["filings"])
    w = config.WEIGHT.get(s["symbol"], 3)
    bonus = min(8.0, w * 0.8)
    st = px.get(s["symbol"]) or {}
    if st and abs(st.get("chg_pct") or 0) >= rules.get("price_move_pct", 4):
        bonus += 6
    if lead.get("category") in rules.get("categories", []):
        bonus += 4
    return round(min(100, m + bonus) if m >= 25 else m, 1)


def digest(hours: float | None = 24, since: str | None = None, rules: dict | None = None,
           muted: list[str] | None = None) -> dict[str, Any]:
    rules = {**config.DEFAULT_RULES, **(rules or {})}
    store = load_store()
    end = now()
    start = _ts(since) if since else end - timedelta(hours=hours or 24)
    items = [it for it in store.values() if (t := _ts(it.get("ts"))) and start <= t <= end and it["symbol"] in config.WEIGHT]
    px = price_stats()
    stories = cluster(items)
    out = []
    for s in stories:
        lead = s["lead"]
        if muted and lead.get("category") in muted:
            continue
        sc = score_story(s, px, rules)
        tier = "matters" if sc >= TIER_MATTERS else "glance" if sc >= TIER_GLANCE else "routine"
        out.append({
            "id": lead["url"], "symbol": s["symbol"], "name": lead.get("name"), "ts": lead.get("ts"),
            "category": lead.get("category"), "label": LABEL.get(lead.get("category"), "Update"),
            "subtype": lead.get("subtype"), "title": lead["title"], "url": lead["url"],
            "oneliner": (lead.get("enrich") or {}).get("line") or (lead.get("enrich") or {}).get("headline") or lead.get("oneliner")
                        or ("Earnings-call transcript is out. Dig in to see what management promised and whether it delivered."
                            if lead.get("subtype") == "transcript" else None),
            "enrich": lead.get("enrich"), "score": sc, "tier": tier,
            "classified_by": lead.get("classified_by"), "source": lead.get("source"),
            "related": [{"title": f["title"], "url": f["url"], "ts": f.get("ts"), "label": LABEL.get(f.get("category"))}
                        for f in s["filings"] if f is not lead],
            "px": {k: (px.get(s["symbol"]) or {}).get(k) for k in ("close", "chg_pct", "vol_x")},
            "weight": config.WEIGHT.get(s["symbol"]),
        })
    out.sort(key=lambda x: (-{"matters": 2, "glance": 1, "routine": 0}[x["tier"]], -x["score"], x["ts"] or ""))
    routine_counts: dict[str, int] = {}
    for x in out:
        if x["tier"] == "routine":
            routine_counts[x["label"]] = routine_counts.get(x["label"], 0) + 1
    return {
        "window": {"start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes")},
        "counts": {"filings": len(items), "stories": len(out),
                   "matters": sum(x["tier"] == "matters" for x in out),
                   "glance": sum(x["tier"] == "glance" for x in out),
                   "routine": sum(x["tier"] == "routine" for x in out)},
        "routine_breakdown": routine_counts,
        "stories": out,
        "alerts": alerts(rules, days=max(1, int(((end - start).total_seconds() + 86399) // 86400))),
        "refreshed": STATUS.get("last_refresh"),
    }


# ----------------------------------------------------------------------------- prices + alerts

def price_history() -> dict[str, list[dict]]:
    return prices.history(config.SYMBOLS)


def price_stats() -> dict[str, dict]:
    try:
        hist = price_history()
    except Exception:  # noqa: BLE001
        return {}
    return {s: prices.stats(rows) for s, rows in hist.items()}


def alerts(rules: dict, days: int = 1, lookback_days: int | None = None) -> list[dict]:
    """Threshold engine over EOD data + material filings. `days` = how many trading
    sessions back to look (1 = last close)."""
    rules = {**config.DEFAULT_RULES, **(rules or {})}
    out: list[dict] = []
    try:
        hist = price_history()
    except Exception:  # noqa: BLE001
        hist = {}
    for s, rows in hist.items():
        evs = prices.daily_events(rows, days=lookback_days or max(1, min(days, 30)))
        for ev in evs:
            if abs(ev["chg_pct"]) >= rules["price_move_pct"]:
                out.append({"type": "price", "symbol": s, "date": ev["date"], "value": ev["chg_pct"],
                            "threshold": rules["price_move_pct"], "vol_x": ev["vol_x"],
                            "msg": f"{'+' if ev['chg_pct'] > 0 else ''}{ev['chg_pct']:.1f}% on {ev['date']}"})
            if ev["vol_x"] and ev["vol_x"] >= rules["volume_multiple"]:
                out.append({"type": "volume", "symbol": s, "date": ev["date"], "value": ev["vol_x"],
                            "threshold": rules["volume_multiple"], "chg_pct": ev["chg_pct"],
                            "msg": f"{ev['vol_x']:.1f}x normal volume on {ev['date']}"})
    store = load_store()
    cutoff = now() - timedelta(days=lookback_days or days)
    seen_evt: set[tuple] = set()
    for it in sorted(store.values(), key=lambda x: -x.get("materiality", 0)):
        t = _ts(it.get("ts"))
        evt = (it["symbol"], (it.get("ts") or "")[:10], it.get("category"))
        if evt in seen_evt:
            continue
        if t and t >= cutoff and it.get("category") in rules["categories"] and it.get("materiality", 0) >= 55:
            seen_evt.add(evt)
            out.append({"type": "filing", "symbol": it["symbol"], "date": it["ts"][:10], "category": it["category"],
                        "label": LABEL.get(it["category"]), "msg": (it.get("enrich") or {}).get("line")
                        or (it.get("enrich") or {}).get("headline") or it["title"], "url": it["url"],
                        "value": it.get("materiality")})
    # Explain *why* a price move happened when a filing landed the same day.
    filing_days = {(it["symbol"], (it.get("ts") or "")[:10]) for it in store.values() if it.get("materiality", 0) >= 38}
    for a in out:
        if a["type"] in ("price", "volume") and (a["symbol"], a["date"]) in filing_days:
            a["explained_by_filing"] = True
    out.sort(key=lambda a: (a["date"], a.get("value") or 0), reverse=True)
    return out


def rules_preview(rules: dict, lookback_days: int = 30) -> dict[str, Any]:
    al = alerts(rules, lookback_days=lookback_days)
    by = {"price": 0, "volume": 0, "filing": 0}
    for a in al:
        by[a["type"]] += 1
    return {"lookback_days": lookback_days, "total": len(al), "by_type": by,
            "per_week": round(len(al) / (lookback_days / 7), 1), "sample": al[:6]}
