import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { Delta, Icon, Sheet, Spark, ago, cr, n } from './ui'

const SORTS = [['attention', 'Needs attention'], ['move', 'Biggest move'], ['weight', 'Position size']]

export default function Holdings({ onOpen }) {
  const [d, setD] = useState(null)
  const [sort, setSort] = useState('attention')
  useEffect(() => { api.portfolio().then(setD).catch(() => setD({ holdings: [] })) }, [])

  const rows = useMemo(() => {
    if (!d) return []
    const h = [...d.holdings]
    if (sort === 'move') h.sort((a, b) => Math.abs(b.px?.chg_pct || 0) - Math.abs(a.px?.chg_pct || 0))
    else if (sort === 'weight') h.sort((a, b) => b.weight - a.weight)
    else h.sort((a, b) => (b.top?.materiality || 0) + (b.px?.vol_x || 0) * 5 - ((a.top?.materiality || 0) + (a.px?.vol_x || 0) * 5))
    return h
  }, [d, sort])

  const dayPnl = d?.holdings?.reduce((s, h) => s + (h.weight * (h.px?.chg_pct || 0)) / 100, 0)

  return (
    <div className="page">
      <div className="hero">
        <div className="eyebrow">Portfolio · 18 holdings{d?.as_of ? ` · close of ${new Date(d.as_of).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}` : ''}</div>
        <h1 className="headline">Your book {dayPnl != null && <>moved <em><Delta v={dayPnl} d={2} /></em></>}</h1>
        <div className="sub">Weighted by position. Tap any name for its filings, numbers and research.</div>
      </div>
      <div className="chips" style={{ marginTop: 12 }}>
        {SORTS.map(([k, l]) => <button key={k} className={`chip ${sort === k ? 'on' : ''}`} onClick={() => setSort(k)}>{l}</button>)}
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        {!d && [...Array(6)].map((_, i) => <div key={i} className="skeleton" style={{ height: 44, margin: 12 }} />)}
        {rows.map((h) => (
          <button key={h.symbol} className="holding" onClick={() => onOpen(h.symbol)}>
            <div style={{ minWidth: 0 }}>
              <div className="row" style={{ gap: 6 }}>
                <span className="sym" style={{ fontSize: 13.5 }}>{h.symbol}</span>
                {h.material_7d > 0 && <span className="badge">{h.material_7d}</span>}
                {h.px?.vol_x >= 2 && <span className="tag warm">{n(h.px.vol_x, 1)}× vol</span>}
              </div>
              <div className="nm">{h.top ? `${h.top.label}: ${h.top.title}` : `${h.sector} · ${h.weight}%`}</div>
            </div>
            <Spark data={h.px?.spark} />
            <div className="px">
              <div className="p">{n(h.px?.close, 1)}</div>
              <div className="c"><Delta v={h.px?.chg_pct} /></div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

export function CompanySheet({ symbol, onClose, onResearch }) {
  const [c, setC] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api.company(symbol).then(setC).catch((e) => setErr(e.message)) }, [symbol])
  return (
    <Sheet onClose={onClose}>
      {err && <div className="empty">{err}</div>}
      {!c && !err && <div className="skeleton" style={{ height: 200 }} />}
      {c && (
        <div className="fadein">
          <div className="row between">
            <span className="sym" style={{ fontSize: 13 }}>{c.symbol}{c.in_portfolio ? ` · ${c.weight}% of book` : ''}</span>
            {c.px && <span className="small muted">52w {n(c.px.lo_52w, 0)}–{n(c.px.hi_52w, 0)}</span>}
          </div>
          <div className="dossier-name">{c.name}</div>
          {c.px && (
            <div className="row" style={{ gap: 12, marginTop: 4 }}>
              <span className="num" style={{ fontSize: 22, fontWeight: 600 }}>₹{n(c.px.close, 1)}</span>
              <Delta v={c.px.chg_pct} />
              <span className="small muted">1m <Delta v={c.px.ret_1m} /> · 3m <Delta v={c.px.ret_3m} /></span>
            </div>
          )}
          <div className="kv">
            <div><div className="k">Mcap</div><div className="v">{n((c.snapshot.market_cap_cr || 0) / 1000, 0)}k</div></div>
            <div><div className="k">P/E</div><div className="v">{n(c.snapshot.pe, 1)}</div></div>
            <div><div className="k">ROCE</div><div className="v">{n(c.snapshot.roce, 0)}%</div></div>
            <div><div className="k">OPM</div><div className="v">{n(c.snapshot.opm_last, 0)}%</div></div>
          </div>
          <button className="btn big" style={{ marginTop: 16 }} onClick={() => onResearch(c.symbol)}>
            {c.research ? 'Open research dossier' : 'Research this company'} {Icon.arrow}
          </button>
          <div className="section">
            <div className="section-h"><h2>Last 5 quarters</h2><span className="count">₹ Cr</span></div>
            <div className="card card-pad" style={{ paddingTop: 6 }}>
              <table className="rt" style={{ marginTop: 0 }}>
                <thead><tr><th>Qtr</th><th>Revenue</th><th>YoY</th><th>PAT</th><th>YoY</th></tr></thead>
                <tbody>
                  {c.quarters.map((q) => (
                    <tr key={q.q}><td>{q.q}</td><td>{n(q.revenue, 0)}</td><td><Delta v={q.rev_yoy} d={0} /></td><td>{n(q.pat, 0)}</td><td><Delta v={q.pat_yoy} d={0} /></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="section">
            <div className="section-h"><h2>Filings</h2><span className="count">{c.filings.length}</span></div>
            <div className="card">
              {c.filings.length === 0 && <div className="empty small">No filings tracked yet{c.in_portfolio ? '' : ' (not in your portfolio)'}.</div>}
              {c.filings.map((f) => (
                <a key={f.url} className="glance-row" href={f.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                  <div className="story-top">
                    <span className={`tag ${f.materiality >= 70 ? 'hot' : f.materiality >= 38 ? 'warm' : ''}`}>{f.label}</span>
                    <span>{ago(f.ts)}</span>
                  </div>
                  <div className="t">{f.enrich?.line || f.enrich?.headline || f.enrich?.takeaway || f.title}</div>
                </a>
              ))}
            </div>
          </div>
        </div>
      )}
    </Sheet>
  )
}
