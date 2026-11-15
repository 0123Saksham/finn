"""Pull side: on-demand research on ANY NSE symbol, grounded only in primary sources.

Pipeline (each step reported live to the UI):
  1. financials  -> Screener's standardised statements -> numbers.analyse()   [code, free]
  2. documents   -> last 4 concall transcripts (+ decks if no transcripts) + latest annual report
  3. read        -> transcripts: fast tier (low thinking); annual report: lite. Cached per doc.
                    (chunked: only guidance-bearing paragraphs / relevant AR pages are sent)
  4. judge       -> promises vs delivered, narrative vs numbers, bull/bear     [deep tier, one call]
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import llm
from ..sources import filings, screener
from ..util import read_cache, write_cache
from . import numbers

log = logging.getLogger("finn.research")
JOBS: dict[str, dict[str, Any]] = {}

GUIDE_WORDS = ("guid", "expect", "target", "outlook", "aspir", "going forward", "next year", "medium term",
               "fy2", "fy 2", "margin", "growth", "capex", "double-digit", "double digit", "%", "crore",
               "we will", "we should", "plan to", "visibility", "pipeline", "order book", "demand")
NOISE = re.compile(r"^(operator|moderator)\b|safe harbo|forward.looking statements|thank you|ladies and gentlemen|"
                   r"press star|question queue|please go ahead|next question", re.I)

TRANSCRIPT_PROMPT = """You are reading an earnings-call transcript of {company} (NSE: {symbol}). Use ONLY this text.
Page markers look like [p.N]. Extract:
{{"period":"quarter discussed, e.g. Q2 FY27 (derive from the text, not the file name)","call_date":"if stated",
 "guidance":[{{"metric":"revenue_growth|margin|ebitda|profit|volume|capex|debt|stores_capacity|other",
   "statement":"<=22 words: what management committed/expects","target":"the number or range, e.g. '15-17%' or 'double-digit'",
   "horizon":"FY27 | H2 FY27 | Q3 FY27 | medium term | ...","quant":true/false,"quote":"<=30 words verbatim","page":int}}],
 "achieved":[{{"claim":"<=18 words: what management says was delivered this quarter","page":int}}],
 "themes":["<=6 words"],
 "pushback":[{{"concern":"<=18 words: what analysts pressed on","answer":"direct|partial|evasive","page":int}}],
 "tone":"confident|measured|cautious|defensive","tone_why":"<=16 words"}}
Max 8 guidance items (prefer quantitative, forward-looking statements on headline numbers), 4 achieved, 5 themes, 4 pushback.

TRANSCRIPT:
{text}"""

DECK_PROMPT = TRANSCRIPT_PROMPT.replace("an earnings-call transcript", "an investor presentation (deck)")

AR_PROMPT = """These are selected pages from {company}'s annual report ({label}). Use ONLY this text; page markers are [p.N].
Return JSON:
{{"fiscal_year":"FYxx","what_they_do":"<=40 words, plain English",
 "segments":[{{"name":str,"share_pct":number|null,"note":"<=12 words"}}],
 "drivers":["<=14 words: what drives the business, per management"],
 "watch":[{{"type":"contingent_liabilities|related_party|auditor|pledge|litigation|other","text":"<=24 words","amount_cr":number|null,"page":int}}]}}
Max 6 segments, 3 drivers, 5 watch items. For 'auditor', note any qualification, emphasis of matter or key audit matter.

PAGES:
{text}"""

JUDGE_PROMPT = """You are a sceptical buy-side analyst. Judge {company}'s management using ONLY the evidence below:
FIN = exchange-reported financials (computed by code — trust these numbers, do not recompute),
T1..Tn = what management said on earnings calls (with page refs), AR = annual report extracts.
Never use outside knowledge about the company. If evidence is missing, say so.
In prose fields, write 'reported numbers' rather than the tag 'FIN'; put tags only in the src fields.

Indian fiscal year: FY27 = Apr 2026–Mar 2027. Q1 = Apr–Jun, Q2 = Jul–Sep, Q3 = Oct–Dec, Q4 = Jan–Mar.

EVIDENCE:
{evidence}

Return JSON:
{{"tldr":"<=35 words: the one thing an investor should know",
 "promises":[{{"promise":"<=18 words","made_in":"e.g. Q4 FY26 call (T3)","target":"","horizon":"",
   "actual":"<=22 words citing FIN numbers","verdict":"delivered|on_track|behind|missed|walked_back|too_early",
   "why":"<=18 words","src":"T3 p.5"}}],
 "credibility":{{"score":0-10,"line":"<=24 words: how reliable this management's guidance has been"}},
 "narrative_vs_numbers":[{{"says":"<=16 words","shows":"<=18 words with numbers","verdict":"agrees|diverges|partly","src":""}}],
 "bull":[{{"point":"<=20 words","evidence":"<=16 words, a number or quote","src":""}}],
 "bear":[{{"point":"<=20 words","evidence":"<=16 words, a number or quote","src":""}}],
 "watch_next":["<=12 words: what would change the view next quarter"]}}
5-8 promises (prefer quantitative guidance on revenue, margins, profit, capex; track the SAME promise across calls when it was restated or revised — 'walked_back' if the target was cut),
3-4 narrative_vs_numbers, exactly 3 bull and 3 bear, 2-3 watch_next."""


def _select_paragraphs(pages: list[str], budget: int = 42000) -> str:
    """Chunking for transcripts: keep paragraphs that carry numbers or forward-looking
    language (plus speaker turns), drop operator/disclaimer noise, keep page markers."""
    paras = []
    for pi, txt in enumerate(pages, 1):
        for para in re.split(r"\n\s*\n|(?<=[.?!])\n(?=[A-Z])", txt):
            p = " ".join(para.split())
            if len(p) < 40 or NOISE.search(p[:80]):
                continue
            low = p.lower()
            score = sum(w in low for w in GUIDE_WORDS) + 2 * bool(re.search(r"\d", p))
            paras.append((pi, score, p))
    full = sum(len(p) for _, _, p in paras)
    if full <= budget:
        keep = paras
    else:
        ranked = sorted(paras, key=lambda x: -x[1])
        chosen, used = set(), 0
        for x in ranked:
            if used > budget:
                break
            chosen.add(id(x))
            used += len(x[2])
        keep = [x for x in paras if id(x) in chosen]
    out, cur = [], None
    for pi, _, p in keep:
        if pi != cur:
            out.append(f"[p.{pi}]")
            cur = pi
        out.append(p)
    return "\n".join(out)


AR_KW = {"segment": 3, "revenue from": 2, "business overview": 4, "our business": 3, "product portfolio": 2,
         "market share": 2, "management discussion": 4, "contingent liabilit": 5, "related party": 3,
         "qualified opinion": 6, "emphasis of matter": 6, "key audit matter": 4, "pledge": 2, "capacity": 1,
         "brands": 1, "customers": 1}


class Job:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.state = {"symbol": symbol, "status": "running", "steps": [], "result": None, "error": None,
                      "started": time.time()}
        self.meter: list = []

    def step(self, text: str, done: bool = False, key: str | None = None):
        key = key or text
        for s in self.state["steps"]:
            if s["key"] == key:
                s.update(text=text, done=done, t=round(time.time() - self.state["started"], 1))
                return
        self.state["steps"].append({"key": key, "text": text, "done": done,
                                    "t": round(time.time() - self.state["started"], 1)})


def _pick_docs(c: dict) -> tuple[list[dict], str]:
    seen, picked = set(), []
    for cc in c["docs"]["concalls"]:
        u = cc.get("transcript")
        if u and u not in seen:
            seen.add(u)
            picked.append({"label": cc["label"], "url": u, "kind": "transcript"})
        if len(picked) == 4:
            break
    if len(picked) >= 2:
        return picked, "transcripts"
    for cc in c["docs"]["concalls"]:
        u = cc.get("ppt")
        if u and u not in seen and u.lower().split("?")[0].endswith(".pdf"):
            seen.add(u)
            picked.append({"label": cc["label"], "url": u, "kind": "deck"})
        if len(picked) == 4:
            break
    return picked, "transcripts + decks" if picked else "none"


def _read_transcript(job: Job, c: dict, i: int, d: dict) -> dict | None:
    tag = f"T{i + 1}"
    key = f"doc-{tag}"
    job.step(f"Reading {d['label']} {d['kind']}…", key=key)
    try:
        pages = filings.pdf_pages(d["url"])
        if filings.is_scanned(pages):
            raw = llm.call("fast", (DECK_PROMPT if d["kind"] == "deck" else TRANSCRIPT_PROMPT).format(
                company=c["name"], symbol=c["symbol"], text="(attached PDF)"), pdf=filings.pdf_bytes(d["url"]),
                meter=job.meter)
        else:
            text = _select_paragraphs(pages)
            raw = llm.call("fast", (DECK_PROMPT if d["kind"] == "deck" else TRANSCRIPT_PROMPT).format(
                company=c["name"], symbol=c["symbol"], text=text), meter=job.meter)
        raw.update(tag=tag, url=d["url"], label=d["label"], kind=d["kind"], pages=len(pages))
        job.step(f"{raw.get('period') or d['label']} {d['kind']}: {len(raw.get('guidance', []))} guidance statements, "
                 f"{len(pages)} pages", done=True, key=key)
        return raw
    except Exception as e:  # noqa: BLE001
        job.step(f"{d['label']} {d['kind']} unreadable ({str(e)[:60]})", done=True, key=key)
        return None


def _read_ar(job: Job, c: dict) -> dict | None:
    ars = c["docs"]["annual_reports"]
    if not ars:
        return None
    ar = ars[0]
    job.step(f"Reading Annual Report {ar['year']}…", key="ar")
    try:
        pages = filings.pdf_pages(ar["url"])
        sel = filings.select_pages(pages, AR_KW, budget_chars=38000)
        text = "\n\n".join(f"[p.{n}]\n{t[:3500]}" for n, t in sel)
        raw = llm.call("lite", AR_PROMPT.format(company=c["name"], label=ar["label"], text=text), meter=job.meter)
        raw.update(url=ar["url"], label=ar["label"], pages_total=len(pages), pages_read=len(sel))
        job.step(f"Annual Report {ar['year']}: read {len(sel)} most relevant of {len(pages)} pages", done=True, key="ar")
        return raw
    except Exception as e:  # noqa: BLE001
        job.step(f"Annual report unavailable ({str(e)[:60]})", done=True, key="ar")
        return None


def _evidence(c: dict, nums: dict, docs: list[dict], ar: dict | None) -> str:
    fin = {"quarters": nums["quarters"], "annual_growth_cagr_pct": nums["growth"], "flags": nums["flags"],
           "balance": nums["balance"], "cash": nums["cash"],
           "annual_opm_pct_last5": nums["series"]["opm"][-5:], "years": nums["years"][-5:]}
    parts = [f"FIN (₹ crore, {nums['basis']}): {json.dumps(fin, ensure_ascii=False)}"]
    for d in sorted(docs, key=lambda x: x["tag"]):
        slim = {k: d.get(k) for k in ("period", "call_date", "guidance", "achieved", "tone", "tone_why", "pushback")}
        parts.append(f"{d['tag']} ({d['kind']}, {d.get('period') or d['label']}): {json.dumps(slim, ensure_ascii=False)}")
    if ar:
        parts.append("AR: " + json.dumps({k: ar.get(k) for k in ("fiscal_year", "what_they_do", "segments", "drivers", "watch")}, ensure_ascii=False))
    return "\n\n".join(parts)


def run(symbol: str, force: bool = False) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    if not force:
        hit = read_cache(f"research/{symbol}")
        if hit:
            return {"symbol": symbol, "status": "done", "steps": hit.get("steps", []), "result": hit, "cached": True}
    j = JOBS.get(symbol)
    if j and j.state["status"] == "running":
        return j.state
    job = Job(symbol)
    JOBS[symbol] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job.state


def status(symbol: str) -> dict[str, Any] | None:
    symbol = symbol.upper()
    j = JOBS.get(symbol)
    if j:
        return j.state
    hit = read_cache(f"research/{symbol}")
    if hit:
        return {"symbol": symbol, "status": "done", "steps": hit.get("steps", []), "result": hit, "cached": True}
    return None


def _run(job: Job):
    s = job.symbol
    try:
        job.step("Pulling 10 years of reported financials…", key="fin")
        c = screener.fetch_company(s, max_age_h=24)
        nums = numbers.analyse(c)
        job.step(f"Financials: {len(nums['years'])} years, {len(nums['quarters'])} quarters, "
                 f"{len(nums['flags'])} rule-based flags", done=True, key="fin")
        picks, mode = _pick_docs(c)
        job.step(f"Found {len(picks)} management documents ({mode}) and "
                 f"{len(c['docs']['annual_reports'])} annual reports", done=True, key="docs")
        if not llm.available():
            raise llm.LLMUnavailable("No model key configured — showing numbers only")
        with ThreadPoolExecutor(max_workers=5) as ex:
            fut_ar = ex.submit(_read_ar, job, c)
            futs = [ex.submit(_read_transcript, job, c, i, d) for i, d in enumerate(picks)]
            docs = [f.result() for f in futs]
            ar = fut_ar.result()
        docs = [d for d in docs if d]
        job.step("Weighing what was promised against what was delivered…", key="judge")
        verdict = llm.call("deep", JUDGE_PROMPT.format(company=c["name"], evidence=_evidence(c, nums, docs, ar)),
                           meter=job.meter, think=True, temperature=0.2) if docs else {}
        job.step("Judgement complete", done=True, key="judge")
        result = {
            "symbol": s, "name": c["name"], "about": c.get("about"), "basis": c.get("basis"),
            "numbers": nums, "docs": [{k: d.get(k) for k in ("tag", "label", "period", "kind", "url", "pages", "tone",
                                                               "tone_why", "themes", "guidance", "pushback", "achieved")}
                                      for d in docs],
            "ar": ar, "verdict": verdict, "cost": llm.summarize_meter(job.meter),
            "steps": job.state["steps"], "generated": time.strftime("%Y-%m-%d %H:%M"),
            "elapsed_s": round(time.time() - job.state["started"], 1),
        }
        write_cache(f"research/{s}", result)
        job.state.update(status="done", result=result)
    except llm.LLMUnavailable as e:
        try:
            c = screener.fetch_company(s)
            nums = numbers.analyse(c)
            job.state.update(status="done", result={"symbol": s, "name": c["name"], "about": c.get("about"),
                                                    "numbers": nums, "docs": [], "ar": None, "verdict": {},
                                                    "note": str(e), "cost": llm.summarize_meter(job.meter),
                                                    "steps": job.state["steps"]})
        except Exception as e2:  # noqa: BLE001
            job.state.update(status="error", error=str(e2))
    except Exception as e:  # noqa: BLE001
        log.exception("research failed")
        job.state.update(status="error", error=str(e)[:300])


# ----------------------------------------------------------------------------- follow-up Q&A

def _chunks(symbol: str) -> list[dict]:
    res = read_cache(f"research/{symbol}")
    if not res:
        return []
    out = []
    srcs = [(d["tag"], d["url"], d.get("period") or d["label"]) for d in res.get("docs", [])]
    if res.get("ar"):
        srcs.append(("AR", res["ar"]["url"], res["ar"].get("label")))
    for tag, url, label in srcs:
        try:
            pages = filings.pdf_pages(url)
        except Exception:  # noqa: BLE001
            continue
        for i, p in enumerate(pages, 1):
            if len(p) > 200:
                out.append({"tag": tag, "label": label, "page": i, "text": p[:4000], "url": url})
    return out


def _bm25(query: str, docs: list[dict], k: int = 6) -> list[dict]:
    import math
    tok = lambda s: re.findall(r"[a-z0-9]+", s.lower())  # noqa: E731
    q = [t for t in tok(query) if len(t) > 2]
    toks = [tok(d["text"]) for d in docs]
    N = len(docs) or 1
    avg = sum(len(t) for t in toks) / N
    df = {w: sum(1 for t in toks if w in t) for w in set(q)}
    scored = []
    for d, t in zip(docs, toks):
        tf = {}
        for w in t:
            if w in df:
                tf[w] = tf.get(w, 0) + 1
        s = sum(math.log(1 + (N - df[w] + .5) / (df[w] + .5)) * tf[w] * 2.2 / (tf[w] + 1.2 * (.25 + .75 * len(t) / avg))
                for w in tf)
        scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return [d for s, d in scored[:k] if s > 0]


ASK_PROMPT = """Answer the investor's question about {company} using ONLY these excerpts from its own filings.
Cite every claim inline like [T2 p.4] or [AR p.112]. If the excerpts don't answer it, say exactly what is missing.
Be concise: <=120 words, numbers first. If you list points, put each on its own line starting with '• '.
Question: {q}
Excerpts:
{ctx}
Return JSON: {{"answer": str, "confidence": "high|medium|low"}}"""


def ask(symbol: str, question: str) -> dict[str, Any]:
    symbol = symbol.upper()
    res = read_cache(f"research/{symbol}")
    if not res:
        return {"answer": "Run the research on this company first — I only answer from its own documents.",
                "confidence": "low", "sources": []}
    hits = _bm25(question, _chunks(symbol))
    if not hits:
        return {"answer": "Nothing in the transcripts or annual report matches that question.", "confidence": "low", "sources": []}
    ctx = "\n\n".join(f"[{h['tag']} p.{h['page']}] ({h['label']})\n{h['text'][:2500]}" for h in hits)
    meter: list = []
    out = llm.call("lite", ASK_PROMPT.format(company=res["name"], q=question, ctx=ctx), meter=meter)
    out["sources"] = [{"tag": h["tag"], "page": h["page"], "label": h["label"], "url": h["url"]} for h in hits]
    out["links"] = {h["tag"]: h["url"] for h in hits}
    out["cost"] = llm.summarize_meter(meter)
    return out
