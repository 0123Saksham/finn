"""Tier-0 classification: exchange subject lines are semi-structured, so ordered regex
rules resolve the large majority for free. Only genuinely ambiguous filings
('General Updates', bare 'Regulation 30' disclosures) go to the cheapest model, batched."""
from __future__ import annotations

import re
from typing import Any

from .. import llm

# (category, subtype, base materiality 0-100, pattern). Order matters: first match wins.
RULES: list[tuple[str, str, int, str]] = [
    ("unclassified", "newspaper_ad", 4, r"newspaper (publication|advertisement)|copy of newspaper"),
    ("earnings_call", "transcript", 42, r"transcript"),
    ("earnings_call", "recording", 8, r"(audio|video).{0,20}recording|recording of (the )?(earnings|analyst|investor)"),
    ("earnings_call", "notice", 10, r"(schedule|intimation).{0,40}(earnings|con(ference)?\.? ?call)|earnings call"),
    ("results", "presentation", 30, r"investor presentation|results presentation|earnings presentation|fact ?sheet"),
    ("results", "board_intimation", 12, r"board meeting intimation|prior intimation"),
    ("results", "financials", 92, r"financial results?|results? for the (quarter|half)|unaudited|audited|outcome.{0,60}result"),
    ("insider_trading", "promoter_deal", 62, r"sast|reg(ulation)?\.? ?29|regulation 7\s*\(2\)|insider trading|\bpit\b"),
    ("pledging", "pledge", 70, r"pledge|encumbrance|reg(ulation)?\.? ?31"),
    ("management_change", "kmp", 84, r"change in (management|kmp|key managerial)|resignation|cessation|appointment of|superannuat|chief (executive|financial)|\bceo\b|\bcfo\b|managing director"),
    ("management_change", "director", 55, r"change in directorate|director"),
    ("M&A", "deal", 80, r"acquisition|amalgamation|merger|demerger|scheme of arrangement|joint venture|disinvestment|sale of (stake|shares)|divest|wholly.owned subsidiary|incorporation of"),
    ("fund_raise", "cp", 12, r"commercial paper"),
    ("fund_raise", "equity", 75, r"\bqip\b|qualified institutions?|rights issue|preferential|buy.?back|fund raising|raising of funds"),
    ("fund_raise", "debt", 35, r"debenture|\bncds?\b|bonds?\b|term loan"),
    ("litigation", "action", 70, r"litigation|penalt|fine[sd]? |\bfines?\b|insolvency|\bcirp\b|nclt|nclat|show cause|tax demand|\bgst\b|order passed|regulatory action|sebi order|dispute|arbitration|court"),
    ("credit_rating", "rating", 38, r"credit rating|rating"),
    ("dividend", "dividend", 32, r"dividend"),
    ("bonus_split", "corp_action", 55, r"bonus|split|sub-division|subdivision"),
    ("capex", "capacity", 62, r"capex|capacity expansion|new (plant|facility)|commissioning|commercial production|greenfield|brownfield"),
    ("postal_ballot", "ballot", 14, r"postal.?ballot|e-voting|scrutini[sz]er"),
    ("agm_egm", "meeting", 14, r"\bagm\b|\begm\b|general meeting"),
    ("investor_meetings", "meet", 6, r"analyst|investor meet|institutional investor|investor conference|roadshow|con\. call updates"),
    ("press_release", "order_win", 52, r"order|contract|bagging|award"),
    ("press_release", "rumour", 45, r"rumou?r|clarification"),
    ("press_release", "business_update", 40, r"production volume|sales volume|business update|operational update|monthly|sales figures|sold"),
    ("press_release", "press", 30, r"press release|media release"),
    ("unclassified", "routine", 3, r"esop|esps|employee stock|allotment|trading window|compliance certificate|reg(ulation)?\.? ?74|74\s*\(5\)|loss of share|duplicate|demat|change in (the )?address|registered office|corporate office|registrar|\brta\b|brsr|esg|secretarial|investor complaint|shareholding pattern|certificate|closure of|record date|reminder"),
]

GENERIC = re.compile(r"^(general updates?|updates?|disclosure|meeting updates)$", re.I)

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
              "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
              "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]

BASE = {}
for c, st, b, _ in RULES:
    BASE.setdefault((c, st), b)


def rule_classify(title: str) -> tuple[str, str, int] | None:
    t = title.lower()
    # Strip the boilerplate prefix so the real subject drives the match.
    t = re.sub(r"announcement under regulation 30 \(lodr\)\s*-?\s*", "", t)
    t = re.sub(r"disclosure under regulation 30.*?(regulations?,? 2015)?", "", t)
    t = re.sub(r"^[\s\-:]+", "", t).strip()
    if not t or GENERIC.search(t):
        return None
    for cat, sub, base, pat in RULES:
        if re.search(pat, t):
            return cat, sub, base
    return None


LLM_PROMPT = """You triage Indian stock-exchange filings for a portfolio investor.
For each filing, pick ONE category from: {cats}.
Also give subtype (short snake_case), materiality 0-100 (how likely it is to change an investor's view of the stock: routine paperwork <10, order wins 40-60, results/M&A/CEO change 80+), and a <=18-word plain-English summary of the fact (no hype).

Filings (JSON): {items}

Return JSON: {{"items":[{{"i":int,"category":str,"subtype":str,"materiality":int,"summary":str}}]}}"""


def classify_all(items: list[dict[str, Any]], meter: list | None = None) -> list[dict[str, Any]]:
    """Mutates and returns items with category/subtype/materiality/how."""
    from ..sources.filings import first_text

    ambiguous = []
    for it in items:
        if it.get("category"):
            continue
        r = rule_classify(it["title"])
        if r:
            it["category"], it["subtype"], it["materiality"] = r
            it["classified_by"] = "rules"
        else:
            ambiguous.append(it)
    if ambiguous and llm.available():
        batch = []
        for i, it in enumerate(ambiguous):
            body = it.get("hint") or ""
            if len(body) < 40 and it.get("url", "").lower().endswith(".pdf"):
                body = first_text(it["url"], 900)  # primary text, first page only
            batch.append({"i": i, "company": it.get("symbol"), "subject": it["title"][:160], "text": body[:900]})
        for start in range(0, len(batch), 25):
            chunk = batch[start:start + 25]
            try:
                out = llm.call("lite", LLM_PROMPT.format(cats=", ".join(CATEGORIES), items=chunk), meter=meter)
                rows = out.get("items", []) if isinstance(out, dict) else out
                for r in rows:
                    it = ambiguous[r["i"]]
                    cat = r.get("category") if r.get("category") in CATEGORIES else "unclassified"
                    it.update(category=cat, subtype=r.get("subtype", "other"),
                              materiality=int(r.get("materiality", 20)), classified_by="llm-lite")
                    if r.get("summary"):
                        it["oneliner"] = r["summary"]
            except Exception as e:  # noqa: BLE001
                import logging
                logging.getLogger("finn.classify").warning("LLM triage failed: %s", e)
    for it in items:
        if not it.get("category"):
            it.update(category="press_release", subtype="general", materiality=25, classified_by="default")
    return items
