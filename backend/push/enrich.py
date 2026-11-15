"""Turn a material filing into something an investor can act on in five seconds.

Spend is proportional to importance:
  results            -> headline P&L read from the actual filing (fast tier), maths in code,
                        cross-checked against exchange-standardised numbers
  management_change  -> who is the person, from the filing's own mandatory 'brief profile'
  other material     -> one line + the key number, sized against the company (lite tier)
  routine            -> nothing (no tokens spent)
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .. import llm
from ..sources import filings

log = logging.getLogger("finn.enrich")

RESULT_KW = {"revenue from operations": 6, "profit before tax": 6, "total income": 3, "finance cost": 3,
             "depreciation": 3, "consolidated": 4, "quarter ended": 3, "net profit": 3, "exceptional": 2,
             "interest earned": 4, "provisions": 2, "lakh": 1, "crore": 1}

RESULTS_PROMPT = """You are extracting the headline P&L from an Indian listed company's quarterly results filing.
Use the CONSOLIDATED statement if present, else standalone. Read figures exactly as printed; do not compute.
Columns needed: the latest quarter (current), the immediately preceding quarter (prev_q), and the same quarter of the previous year (yoy_q).
Fields per column (numbers, in the filing's unit; null if absent):
 revenue (revenue from operations), other_income, finance_costs, depreciation, exceptional_items (signed as it affects profit: a loss is negative),
 pbt (profit before tax), pat (net profit for the period), pat_owners (attributable to owners, if shown)
 For banks/NBFCs also: interest_earned, interest_expended, operating_profit (before provisions & contingencies), provisions.
Return JSON:
{{"basis":"consolidated|standalone","unit":"crore|lakh|million|thousand","is_lender":bool,
 "labels":{{"current":"e.g. Q2 FY27 (quarter ended 30-Sep-2026)","prev_q":"...","yoy_q":"..."}},
 "current":{{...}},"prev_q":{{...}},"yoy_q":{{...}},"page_hint":int|null}}
{body}"""

MGMT_PROMPT = """This is an Indian stock-exchange filing about a management/board change. SEBI rules require such filings to include
a 'brief profile' of any person appointed. Extract only what the filing says.
Return JSON: {{"changes":[{{"person":str,"role":str,"action":"appointed|resigned|retired|reappointed|ceased|redesignated|superannuated",
 "effective":str|null,"seniority":"ceo_cfo_md|whole_time_director|independent_director|business_head|other_kmp",
 "reason":str|null,"successor":str|null,
 "bio":{{"summary":"<=28 words: who they are, where they came from","prior":["Org - role"...<=4],"education":str|null,"years_experience":int|null}}}}],
 "top_change": true only if someone joins or leaves as CEO/MD/CFO/Chairman of the company itself (NOT re-appointments, NOT additional-charge handovers, NOT division heads or independent directors),
 "headline":"<=14 words, plain English, e.g. 'CFO X resigns; Y (ex-Z) takes over from 1 Dec'"}}
Filing subject: {title}
Filing text:
{body}"""

ONELINER_PROMPT = """You brief a busy portfolio investor on one stock-exchange filing by {company}.
Subject: {title}
Text (first pages): {body}
Return JSON: {{"line":"<=20 words: the fact that matters, with the key number. No adjectives, no hype.",
 "amount_inr_cr": number|null (the main rupee amount involved, converted to crore; null if none),
 "amount_kind":"order|penalty|tax_demand|investment|consideration|borrowing|dividend_per_share|other|null",
 "direction":"positive|negative|neutral",
 "rating_action":"upgrade|downgrade|reaffirm|withdrawn|outlook_positive|outlook_negative|null",
 "materiality_hint":0-100}}"""

_UNIT = {"crore": 1.0, "lakh": 0.01, "lakhs": 0.01, "million": 0.1, "mn": 0.1, "thousand": 0.0001}


def _cr(v, unit):
    if v is None:
        return None
    try:
        return float(v) * _UNIT.get((unit or "crore").lower(), 1.0)
    except (TypeError, ValueError):
        return None


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100 * (1 if b > 0 else -1), 1)


def _ebitda(col: dict) -> float | None:
    pbt, fin, dep = col.get("pbt"), col.get("finance_costs"), col.get("depreciation")
    if pbt is None or fin is None or dep is None:
        return None
    exc = col.get("exceptional_items") or 0
    oi = col.get("other_income") or 0
    return pbt - exc + fin + dep - oi


def results_card(item: dict, company: dict | None, meter: list) -> dict | None:
    url = item["url"]
    try:
        pages = filings.pdf_pages(url)
    except Exception as e:  # noqa: BLE001
        log.warning("results pdf failed %s: %s", url, e)
        return None
    if filings.is_scanned(pages):
        raw = llm.call("fast", RESULTS_PROMPT.format(body="(the filing is attached as a PDF)"),
                       pdf=filings.pdf_bytes(url), meter=meter)
        route = "fast · PDF vision (scanned filing)"
    else:
        sel = filings.select_pages(pages, RESULT_KW, budget_chars=16000)
        body = "\n\n".join(f"[page {n}]\n{t}" for n, t in sel)
        raw = llm.call("fast", RESULTS_PROMPT.format(body="Filing text (relevant pages only):\n" + body), meter=meter)
        route = f"fast · text of {len(sel)}/{len(pages)} pages"
    unit = raw.get("unit", "crore")
    cols = {}
    for k in ("current", "prev_q", "yoy_q"):
        c = {f: _cr(v, unit) for f, v in (raw.get(k) or {}).items()}
        if c.get("pat_owners") is not None:
            c["pat"] = c["pat_owners"]
        c["ebitda"] = None if raw.get("is_lender") else _ebitda(c)
        cols[k] = c
    cur = cols["current"]
    lender = bool(raw.get("is_lender")) or bool(company and company.get("is_financial"))
    metrics = ["revenue", "operating_profit", "pbt", "pat"] if lender else ["revenue", "ebitda", "pbt", "pat"]
    rows = []
    for m in metrics:
        v = cur.get(m)
        rows.append({"metric": {"revenue": "Revenue", "ebitda": "EBITDA", "operating_profit": "Op. profit (PPOP)",
                                "pbt": "PBT", "pat": "PAT"}[m],
                     "value": None if v is None else round(v, 1),
                     "qoq": _pct(v, cols["prev_q"].get(m)), "yoy": _pct(v, cols["yoy_q"].get(m))})
    margin = None
    if not lender and cur.get("ebitda") and cur.get("revenue"):
        margin = {"now": round(cur["ebitda"] / cur["revenue"] * 100, 1)}
        for k in ("prev_q", "yoy_q"):
            c = cols[k]
            if c.get("ebitda") and c.get("revenue"):
                margin[k] = round(c["ebitda"] / c["revenue"] * 100, 1)
    check = _crosscheck(cur, company)
    return {"kind": "results", "labels": raw.get("labels", {}), "basis": raw.get("basis"),
            "rows": rows, "margin": margin, "lender": lender, "check": check, "route": route,
            "takeaway": _results_takeaway(rows, margin)}


def _crosscheck(cur: dict, company: dict | None) -> dict | None:
    """Independent check of the model's extraction against Screener's standardised quarter."""
    if not company or not company.get("quarters"):
        return None
    q = company["quarters"]["rows"]
    sales = q.get("Sales") or q.get("Revenue")
    np_ = q.get("Net Profit")
    if not sales or cur.get("revenue") is None:
        return None
    ref = sales[-1]
    ok = ref is not None and abs(cur["revenue"] - ref) / max(1, abs(ref)) < 0.02
    out = {"revenue_ref": ref, "match": ok, "period": company["quarters"]["periods"][-1]}
    if np_ and np_[-1] is not None and cur.get("pat") is not None:
        out["pat_ref"] = np_[-1]
    return out


def _results_takeaway(rows, margin) -> str:
    r = {x["metric"]: x for x in rows}
    rev, pat = r.get("Revenue", {}), r.get("PAT", {})
    bits = []
    if rev.get("yoy") is not None:
        bits.append(f"Revenue {rev['yoy']:+.0f}% YoY")
    if pat.get("yoy") is not None:
        bits.append(f"PAT {pat['yoy']:+.0f}% YoY")
    if margin and margin.get("yoy_q") is not None:
        d = round((margin["now"] - margin["yoy_q"]) * 100)
        bits.append(f"EBITDA margin {margin['now']:.1f}% ({d:+d} bps YoY)")
    return " · ".join(bits)


def mgmt_card(item: dict, meter: list) -> dict | None:
    try:
        pages = filings.pdf_pages(item["url"])
    except Exception:
        pages = []
    if pages and not filings.is_scanned(pages):
        out = llm.call("lite", MGMT_PROMPT.format(title=item["title"], body="\n".join(pages)[:9000]), meter=meter)
    elif item["url"].lower().endswith(".pdf") or pages:
        out = llm.call("fast", MGMT_PROMPT.format(title=item["title"], body="(attached PDF)"),
                       pdf=filings.pdf_bytes(item["url"]), meter=meter)
    else:
        return None
    changes = out.get("changes") or []
    for c in changes:
        name = re.sub(r"^(mr|ms|mrs|dr|shri|smt)\.?\s+", "", c.get("person", ""), flags=re.I)
        c["linkedin"] = "https://www.linkedin.com/search/results/people/?keywords=" + re.sub(r"\s+", "%20", name)
    return {"kind": "people", "changes": changes, "headline": out.get("headline"), "top_change": bool(out.get("top_change"))}


def oneliner(item: dict, company: dict | None, meter: list) -> dict | None:
    body = item.get("hint", "")
    if item["url"].lower().endswith(".pdf"):
        body = filings.first_text(item["url"], 3500) or body
    if not body:
        return None
    out = llm.call("lite", ONELINER_PROMPT.format(company=item.get("name") or item["symbol"], title=item["title"],
                                                  body=body[:3500]), meter=meter)
    res = {"kind": "line", "line": out.get("line"), "direction": out.get("direction"),
           "rating_action": out.get("rating_action")}
    amt = out.get("amount_inr_cr")
    if amt and company and out.get("amount_kind") in ("order", "penalty", "tax_demand", "investment", "consideration"):
        rev = _ttm(company, "Sales") or _ttm(company, "Revenue")
        pat = _ttm(company, "Net Profit")
        kind = out.get("amount_kind")
        base, label = (pat, "of TTM profit") if kind in ("penalty", "tax_demand") else (rev, "of TTM revenue")
        if base:
            res["scale"] = {"amount_cr": amt, "pct": round(amt / base * 100, 2), "of": label, "kind": kind}
    res["materiality_hint"] = out.get("materiality_hint")
    return res


def _ttm(company: dict, row: str) -> float | None:
    q = company.get("quarters", {}).get("rows", {}).get(row)
    if not q:
        return None
    vals = [v for v in q[-4:] if v is not None]
    return sum(vals) if len(vals) == 4 else None


def adjust_materiality(item: dict) -> int:
    """Second pass: the base score from the category, sharpened by what we learned."""
    m = item.get("materiality", 20)
    e = item.get("enrich") or {}
    if e.get("kind") == "people":
        sen = [c.get("seniority") for c in e.get("changes", [])]
        acts = [c.get("action") for c in e.get("changes", [])]
        if e.get("top_change"):
            m = max(m, 88)
        elif acts and all(a == "reappointed" for a in acts):
            m = min(m, 35)
        elif "business_head" in sen or "whole_time_director" in sen:
            m = min(max(m, 50), 62)
        elif sen and all(s == "independent_director" for s in sen):
            m = min(m, 45)
        else:
            m = min(m, 55)
    if e.get("kind") == "line":
        sc = e.get("scale")
        if sc:
            p = sc["pct"]
            if sc["kind"] in ("penalty", "tax_demand"):
                m = 25 if p < 0.5 else 60 if p < 5 else 85
            elif sc["kind"] == "order":
                m = 30 if p < 1 else 55 if p < 5 else 78
            elif sc["kind"] in ("investment", "consideration"):
                m = max(m, 45 if p < 2 else 75)
        ra = e.get("rating_action")
        if ra in ("upgrade", "downgrade", "outlook_negative"):
            m = max(m, 62)
        elif ra in ("reaffirm", "withdrawn"):
            m = min(m, 22)
        if e.get("materiality_hint") is not None and not sc and not ra:
            m = round((m + int(e["materiality_hint"])) / 2)
    return int(m)


def enrich(item: dict, company: dict | None, meter: list) -> dict | None:
    cat, sub = item.get("category"), item.get("subtype")
    try:
        if cat == "results" and sub == "financials" and item["url"].lower().endswith(".pdf"):
            return results_card(item, company, meter)
        if cat == "management_change":
            return mgmt_card(item, meter)
        if item.get("materiality", 0) >= 30 and cat not in ("earnings_call", "investor_meetings", "unclassified"):
            return oneliner(item, company, meter)
    except llm.LLMUnavailable:
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("enrich failed for %s: %s", item.get("title"), e)
    return None
