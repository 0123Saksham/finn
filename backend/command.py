"""One natural-language entry point for the whole app ("copilot" interaction model).

  "what happened at HAL"            -> open HAL's sheet
  "research pidilite"               -> start a dossier
  "ping me if anything moves 3%"    -> change an alert rule
  "what did infosys say on margins" -> grounded Q&A over that company's filings
  "what matters this week"          -> brief, 7-day window

Rules resolve the common phrasings for free; only free-form requests reach flash-lite.
"""
from __future__ import annotations

import re
from typing import Any

from . import config, llm
from .sources import screener
from .util import http_get, read_cache

INTENT_PROMPT = """You route a portfolio investor's request inside an investing app. Portfolio symbols: {syms}.
Request: "{text}"
Return JSON: {{"intent":"brief|company|research|ask|rules","company":str|null (name or ticker as said),
 "question":str|null (for ask), "window_hours":int|null, "price_move_pct":number|null, "volume_multiple":number|null}}
- brief: what's new / what matters / summary of the portfolio (window_hours if a period is named)
- company: quick look at one company's latest news or filings
- research: deep analysis / dossier / should I worry about X / is management credible
- ask: a specific factual question about one company's commentary or guidance
- rules: change alert thresholds"""


def _resolve(name: str | None) -> dict[str, str] | None:
    if not name:
        return None
    n = name.strip().upper().replace(" ", "")
    if n in config.WEIGHT:
        return {"symbol": n, "name": n}
    low = name.lower().strip()
    for s in config.SYMBOLS:  # portfolio first: "hdfc" should mean the holding, not a random HDFC entity
        c = read_cache(f"screener/{s}") or {}
        if low and (low in (c.get("name") or "").lower() or low == s.lower()):
            return {"symbol": s, "name": c.get("name", s)}
    try:
        from urllib.parse import quote
        r = http_get(f"https://www.screener.in/api/company/search/?q={quote(name)}&v=3&fts=1").json()
        for x in r:
            m = re.search(r"/company/([^/]+)/", x.get("url", ""))
            if m and m.group(1) != "id" and not m.group(1).isdigit():
                return {"symbol": m.group(1), "name": x["name"]}
    except Exception:  # noqa: BLE001
        pass
    return None


RULES = [
    (r"\b(research|analy[sz]e|deep ?dive|dossier|dig into)\b\s*(?:on|into|of)?\s*(?P<co>[\w&.\- ]+)?", "research"),
    (r"\b(what happened (at|to|with)|news on|latest (on|from)|filings? (of|for|from)|open)\s+(?P<co>[\w&.\- ]+)", "company"),
    (r"\b(what('?s| is) new|what matters|brief|summary|catch me up|morning|today)\b", "brief"),
    (r"\b(alert|ping|notify|tell) me\b.*?(?P<pct>\d+(\.\d+)?)\s*(%|percent)", "rules_pct"),
    (r"\b(alert|ping|notify|tell) me\b.*?(?P<vx>\d+(\.\d+)?)\s*(x|times)\b.*volume|volume.*?(?P<vx2>\d+(\.\d+)?)\s*(x|times)", "rules_vol"),
]


def _window(text: str) -> int | None:
    t = text.lower()
    if "week" in t:
        return 168
    if "month" in t:
        return 720
    if "3 day" in t or "three day" in t:
        return 72
    if "today" in t or "24" in t:
        return 24
    return None


def route(text: str) -> dict[str, Any]:
    t = text.strip()
    low = t.lower()
    how = "rules"
    intent: dict[str, Any] | None = None
    for pat, kind in RULES:
        m = re.search(pat, low)
        if not m:
            continue
        if kind in ("research", "company"):
            co = (m.groupdict().get("co") or "").strip(" ?.")
            co = re.sub(r"\b(the|stock|shares?|company|ltd|limited|please)\b", "", co).strip()
            if co:
                intent = {"intent": kind, "company": co}
                break
        elif kind == "brief":
            intent = {"intent": "brief", "window_hours": _window(low)}
            break
        elif kind == "rules_pct":
            intent = {"intent": "rules", "price_move_pct": float(m.group("pct"))}
            break
        elif kind == "rules_vol":
            intent = {"intent": "rules", "volume_multiple": float(m.group("vx") or m.group("vx2"))}
            break
    if intent is None and llm.available():
        how = "flash-lite"
        try:
            intent = llm.call("lite", INTENT_PROMPT.format(syms=", ".join(config.SYMBOLS), text=t[:300]))
        except Exception:  # noqa: BLE001
            intent = None
    if intent is None:
        co = _resolve(t)
        intent = {"intent": "research", "company": t} if co else {"intent": "brief"}
    out: dict[str, Any] = {"intent": intent.get("intent", "brief"), "routed_by": how}
    if intent.get("company"):
        co = _resolve(intent["company"])
        if not co:
            return {"intent": "error", "message": f"I couldn't find a listed company called \"{intent['company']}\"."}
        out.update(co)
    if out["intent"] == "ask":
        if out.get("symbol") and read_cache(f"research/{out['symbol']}"):
            from .pull import research
            out["answer"] = research.ask(out["symbol"], intent.get("question") or t)
        else:
            out["intent"] = "research"  # need the documents read first
    if out["intent"] == "brief":
        out["window_hours"] = intent.get("window_hours")
    if out["intent"] == "rules":
        out["rules"] = {k: intent[k] for k in ("price_move_pct", "volume_multiple") if intent.get(k)}
    return out
