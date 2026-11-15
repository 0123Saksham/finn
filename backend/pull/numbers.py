"""Deterministic financial analysis. No model touches arithmetic: growth, margins,
leverage, cash conversion and working capital are computed here, and the model only
ever *reads* these numbers. Flags are explicit rules an analyst can audit."""
from __future__ import annotations

from typing import Any


def _row(tbl: dict | None, *names: str) -> list[float | None]:
    if not tbl:
        return []
    for n in names:
        for k, v in tbl["rows"].items():
            if k.lower().startswith(n.lower()):
                return v
    return []


def _annual(tbl: dict | None, *names: str, drop_ttm: bool = True) -> list[tuple[str, float | None]]:
    if not tbl:
        return []
    vals = _row(tbl, *names)
    pairs = list(zip(tbl["periods"], vals))
    if drop_ttm:
        pairs = [(p, v) for p, v in pairs if p.upper() != "TTM"]
    return pairs


def cagr(series: list[tuple[str, float | None]], years: int) -> float | None:
    s = [(p, v) for p, v in series if v is not None]
    if len(s) <= years:
        return None
    a, b = s[-1 - years][1], s[-1][1]
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return round(((b / a) ** (1 / years) - 1) * 100, 1)


def _last(series, n=1):
    s = [v for _, v in series if v is not None]
    return s[-n:] if s else []


def _fy(p: str) -> str:
    # 'Mar 2026' -> 'FY26'
    try:
        return "FY" + p.split()[-1][-2:]
    except Exception:
        return p


def _qlabel(p: str) -> str:
    # 'Sep 2026' -> 'Q2 FY27'
    m, y = p.split()
    y = int(y)
    q = {"Jun": 1, "Sep": 2, "Dec": 3, "Mar": 4}.get(m)
    if not q:
        return p
    fy = y + 1 if q in (1, 2, 3) else y
    return f"Q{q} FY{str(fy)[-2:]}"


def analyse(c: dict[str, Any]) -> dict[str, Any]:
    pl, bs, cf, eff, qt = c.get("pl"), c.get("bs"), c.get("cf"), c.get("eff"), c.get("quarters")
    fin = c.get("is_financial")
    sales = _annual(pl, "Sales", "Revenue")
    op = _annual(pl, "Financing Profit" if fin else "Operating Profit")
    opm = _annual(pl, "Financing Margin" if fin else "OPM")
    pat = _annual(pl, "Net Profit")
    pbt = _annual(pl, "Profit before tax")
    interest = _annual(pl, "Interest")
    cfo = _annual(cf, "Cash from Operating")
    fcf = _annual(cf, "Free Cash Flow")
    borrow = _annual(bs, "Borrowings", "Borrowing", drop_ttm=False)
    eq = [(p, (a or 0) + (b or 0)) for (p, a), (_, b) in zip(_annual(bs, "Equity Capital", drop_ttm=False), _annual(bs, "Reserves", drop_ttm=False))]
    roce = _annual(eff, "ROCE", "ROE")
    debtor = _annual(eff, "Debtor Days")
    inv = _annual(eff, "Inventory Days")
    ccc = _annual(eff, "Cash Conversion Cycle")
    wcd = _annual(eff, "Working Capital Days")

    years = [_fy(p) for p, _ in sales][-10:]
    out: dict[str, Any] = {"basis": c.get("basis"), "is_financial": fin, "years": years}

    def tail(series, n=10):
        return [v for _, v in series][-n:]

    out["series"] = {
        "revenue": tail(sales), "op_profit": tail(op), "opm": tail(opm), "pat": tail(pat),
        "cfo": tail(cfo), "fcf": tail(fcf), "roce": tail(roce),
        "debtor_days": tail(debtor), "inventory_days": tail(inv), "ccc": tail(ccc), "wc_days": tail(wcd),
        "borrowings": [v for _, v in borrow][-10:], "equity": [v for _, v in eq][-10:],
    }
    out["growth"] = {
        "revenue": {"3y": cagr(sales, 3), "5y": cagr(sales, 5), "10y": cagr(sales, 9)},
        "op_profit": {"3y": cagr(op, 3), "5y": cagr(op, 5)},
        "pat": {"3y": cagr(pat, 3), "5y": cagr(pat, 5), "10y": cagr(pat, 9)},
    }
    # Quarterly: last 8 quarters with YoY, the backbone for promise-vs-delivery.
    q_sales = _row(qt, "Sales", "Revenue")
    q_op = _row(qt, "Financing Profit" if fin else "Operating Profit")
    q_opm = _row(qt, "Financing Margin" if fin else "OPM")
    q_pat = _row(qt, "Net Profit")
    qp = qt["periods"] if qt else []
    quarters = []
    for i in range(len(qp)):
        def yoy(arr):
            if i >= 4 and arr and arr[i] is not None and arr[i - 4] not in (None, 0):
                return round((arr[i] / arr[i - 4] - 1) * 100 * (1 if arr[i - 4] > 0 else -1), 1)
            return None
        quarters.append({"q": _qlabel(qp[i]), "period": qp[i],
                         "revenue": q_sales[i] if i < len(q_sales) else None, "rev_yoy": yoy(q_sales),
                         "op_profit": q_op[i] if i < len(q_op) else None, "op_yoy": yoy(q_op),
                         "opm": q_opm[i] if i < len(q_opm) else None,
                         "pat": q_pat[i] if i < len(q_pat) else None, "pat_yoy": yoy(q_pat)})
    out["quarters"] = quarters[-9:]

    # Balance sheet + cash quality.
    b_last = _last(borrow)
    e_last = _last(eq)
    de = round(b_last[0] / e_last[0], 2) if b_last and e_last and e_last[0] else None
    ic = None
    if pbt and interest and _last(interest) and _last(interest)[0]:
        ic = round((_last(pbt)[0] + _last(interest)[0]) / _last(interest)[0], 1)
    cfo5, pat5 = _last(cfo, 5), _last(pat, 5)
    conv = round(sum(cfo5) / sum(pat5), 2) if len(cfo5) == 5 and len(pat5) == 5 and sum(pat5) > 0 else None
    fcf5 = round(sum(_last(fcf, 5)), 0) if len(_last(fcf, 5)) == 5 else None
    out["balance"] = {"debt_to_equity": de, "borrowings": b_last[0] if b_last else None,
                      "interest_cover": ic, "borrowings_3y_ago": _last(borrow, 4)[0] if len(_last(borrow, 4)) == 4 else None}
    out["cash"] = {"cfo_to_pat_5y": conv, "fcf_5y_sum": fcf5,
                   "cfo_last": _last(cfo)[0] if _last(cfo) else None, "pat_last": _last(pat)[0] if _last(pat) else None}
    out["snapshot"] = {
        "market_cap_cr": c["ratios"].get("Market Cap"), "price": c["ratios"].get("Current Price"),
        "pe": c["ratios"].get("Stock P/E"), "roce": c["ratios"].get("ROCE"), "roe": c["ratios"].get("ROE"),
        "div_yield": c["ratios"].get("Dividend Yield"),
        "ttm_revenue": _annual(pl, "Sales", "Revenue", drop_ttm=False)[-1][1] if pl else None,
        "ttm_pat": _annual(pl, "Net Profit", drop_ttm=False)[-1][1] if pl else None,
        "opm_last": _last(opm)[0] if _last(opm) else None,
    }
    out["flags"] = flags(out, fin)
    return out


def flags(a: dict, fin: bool) -> list[dict[str, str]]:
    """Explicit, auditable rules. Each flag says what it measured."""
    f: list[dict[str, str]] = []
    s, g = a["series"], a["growth"]

    def add(level, area, text):
        f.append({"level": level, "area": area, "text": text})

    opm = [v for v in s["opm"] if v is not None]
    if len(opm) >= 4 and not fin:
        d = opm[-1] - opm[-4]
        if d <= -3:
            add("red", "Trajectory", f"Operating margin compressed {abs(d):.1f} pts in 3 years ({opm[-4]:.0f}% → {opm[-1]:.0f}%).")
        elif d >= 3:
            add("green", "Trajectory", f"Operating margin expanded {d:.1f} pts in 3 years ({opm[-4]:.0f}% → {opm[-1]:.0f}%).")
    rg, pg = g["revenue"]["3y"], g["pat"]["3y"]
    if rg is not None and pg is not None:
        if pg - rg >= 8:
            add("green", "Trajectory", f"Profit compounding faster than sales (PAT {pg}% vs revenue {rg}% 3y CAGR) — operating leverage.")
        elif rg - pg >= 8:
            add("amber", "Trajectory", f"Sales growing faster than profit (revenue {rg}% vs PAT {pg}% 3y CAGR) — growth is getting more expensive.")
    conv = a["cash"]["cfo_to_pat_5y"]
    if conv is not None and not fin:
        if conv < 0.7:
            add("red", "Cash quality", f"Only {conv:.2f}x of 5-year profit arrived as operating cash — profits are not converting.")
        elif conv >= 1.0:
            add("green", "Cash quality", f"Operating cash ≥ reported profit over 5 years ({conv:.2f}x) — earnings are real.")
    fcf = a["cash"]["fcf_5y_sum"]
    if fcf is not None and fcf < 0 and not fin:
        add("amber", "Cash quality", f"Negative cumulative free cash flow over 5 years (₹{fcf:,.0f} Cr) — growth is being funded externally.")
    de = a["balance"]["debt_to_equity"]
    if de is not None and not fin:
        if de > 1:
            add("red", "Balance sheet", f"Debt/equity of {de:.2f} — leveraged.")
        elif de < 0.1:
            add("green", "Balance sheet", f"Debt/equity {de:.2f} — effectively debt-free.")
    b, b3 = a["balance"]["borrowings"], a["balance"]["borrowings_3y_ago"]
    if b and b3 and b3 > 0 and b / b3 > 2 and not fin and b > 500:
        add("amber", "Balance sheet", f"Borrowings up {b / b3:.1f}x in ~3 years (₹{b3:,.0f} → ₹{b:,.0f} Cr).")
    ic = a["balance"]["interest_cover"]
    if ic is not None and ic < 3 and not fin:
        add("red", "Balance sheet", f"Interest cover only {ic:.1f}x.")
    dd = [v for v in s["debtor_days"] if v is not None]
    if len(dd) >= 4 and dd[-4] and dd[-1] - dd[-4] > 15 and dd[-1] / dd[-4] > 1.3:
        add("amber", "Working capital", f"Debtor days stretched from {dd[-4]:.0f} to {dd[-1]:.0f} in 3 years — customers paying slower.")
    cc = [v for v in s["ccc"] if v is not None]
    if len(cc) >= 4 and cc[-1] - cc[-4] > 20:
        add("amber", "Working capital", f"Cash conversion cycle lengthened {cc[-4]:.0f} → {cc[-1]:.0f} days.")
    elif len(cc) >= 4 and cc[-4] - cc[-1] > 20:
        add("green", "Working capital", f"Cash conversion cycle tightened {cc[-4]:.0f} → {cc[-1]:.0f} days.")
    return f
