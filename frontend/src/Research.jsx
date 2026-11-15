import { useEffect, useRef, useState } from 'react'
import { api, store } from './api'
import { Bars, Delta, Icon, cr, n } from './ui'

const VERDICT = {
  delivered: ['Delivered', 'v-good'], on_track: ['On track', 'v-good'], behind: ['Behind', 'v-mid'],
  too_early: ['Too early', 'v-na'], missed: ['Missed', 'v-bad'], walked_back: ['Walked back', 'v-bad'],
}
const SAYS = { agrees: ['Agrees', 'v-good'], partly: ['Partly', 'v-mid'], diverges: ['Diverges', 'v-bad'] }

const clean = (t) => (typeof t === 'string' ? t.replace(/FIN (shows|reports)/g, 'Reported numbers show').replace(/(in|per|from) FIN/g, '$1 reported numbers').replace(/FIN/g, 'reported numbers') : t)
const deepClean = (o) => (Array.isArray(o) ? o.map(deepClean) : o && typeof o === 'object' ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, k === 'src' ? v : deepClean(v)])) : clean(o))

export function useVoice(onText) {
  const [on, setOn] = useState(false)
  const R = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
  const start = () => {
    if (!R) return alert('Voice input needs Chrome or Safari.')
    const r = new R()
    r.lang = 'en-IN'; r.interimResults = false; r.maxAlternatives = 1
    r.onresult = (e) => onText(e.results[0][0].transcript)
    r.onend = () => setOn(false)
    r.onerror = () => setOn(false)
    r.start(); setOn(true)
  }
  return { on, start, supported: !!R }
}

function Src({ s, links }) {
  if (!s) return null
  const parts = String(s).split(/[,;/]/).map((x) => x.trim()).filter(Boolean).slice(0, 2)
  return parts.map((p) => {
    const m = p.match(/(T\d|AR)\W*p?\.?\s*(\d+)?/i)
    const url = m && links[m[1].toUpperCase()]
    return url ? (
      <a key={p} className="src" href={`${url}${m[2] ? `#page=${m[2]}` : ''}`} target="_blank" rel="noreferrer">{p}</a>
    ) : <span key={p} className="src">{p}</span>
  })
}

function Steps({ steps, running }) {
  return (
    <div className="steps">
      {steps.map((s) => (
        <div key={s.key} className="step fadein">
          <span className={`ic ${s.done ? 'done' : 'run'}`}>{s.done ? '✓' : ''}</span>
          <span className="grow">{s.text}</span>
          <span className="tm">{s.t}s</span>
        </div>
      ))}
      {running && steps.every((s) => s.done) && <div className="step"><span className="ic run" /><span className="muted">Working…</span></div>}
    </div>
  )
}

function Promises({ v, links }) {
  const [open, setOpen] = useState(null)
  const list = v.promises || []
  const tally = list.reduce((a, p) => ({ ...a, [p.verdict]: (a[p.verdict] || 0) + 1 }), {})
  const c = v.credibility || {}
  const col = c.score >= 7 ? 'var(--up)' : c.score >= 4.5 ? 'var(--glance)' : 'var(--down)'
  return (
    <>
      <div className="card cred">
        <div>
          <div className="cred-score" style={{ color: col }}>{c.score ?? '–'}<small>/10</small></div>
          <div className="tiny muted" style={{ marginTop: 4 }}>Guidance credibility</div>
        </div>
        <div className="grow">
          <div className="small">{c.line}</div>
          <div className="meter"><span style={{ width: `${(c.score || 0) * 10}%`, background: col }} /></div>
          <div className="row wrap tiny muted" style={{ gap: 10, marginTop: 6 }}>
            {Object.entries(tally).map(([k, x]) => <span key={k}>{VERDICT[k]?.[0] || k} <b className="num">{x}</b></span>)}
          </div>
        </div>
      </div>
      <div className="section-h" style={{ marginTop: 20 }}><h2>Said vs done</h2><span className="count">{list.length} promises tracked</span></div>
      <div className="card">
        {list.map((p, i) => {
          const [lab, cl] = VERDICT[p.verdict] || [p.verdict, 'v-na']
          return (
            <button key={i} className="promise" onClick={() => setOpen(open === i ? null : i)}>
              <div className="row" style={{ alignItems: 'flex-start', gap: 10 }}>
                <span className={`verdict ${cl}`}>{lab}</span>
                <span className="grow" style={{ fontWeight: 500, fontSize: 14.5 }}>{p.promise}</span>
              </div>
              <div className="pv">
                <span className="l">Said</span><span>{p.target}{p.horizon ? <span className="muted"> · {p.horizon}</span> : ''} <span className="muted">— {p.made_in}</span></span>
                <span className="l">Done</span><span>{p.actual}</span>
              </div>
              {open === i && (
                <div className="fadein small ink2" style={{ marginTop: 8 }}>
                  {p.why} <Src s={p.src} links={links} />
                </div>
              )}
            </button>
          )
        })}
      </div>
      {(v.narrative_vs_numbers || []).length > 0 && (
        <>
          <div className="section-h" style={{ marginTop: 22 }}><h2>Narrative vs numbers</h2></div>
          <div className="card">
            {v.narrative_vs_numbers.map((x, i) => {
              const [lab, cl] = SAYS[x.verdict] || [x.verdict, 'v-na']
              return (
                <div key={i} className="says">
                  <div className="row between"><span className={`verdict ${cl}`}>{lab}</span><Src s={x.src} links={links} /></div>
                  <div className="pv">
                    <span className="l">Says</span><span style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 15 }}>{x.says}</span>
                    <span className="l">Shows</span><span>{x.shows}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </>
  )
}

function Case({ v, links }) {
  const side = (title, arr, color) => (
    <>
      <div className="section-h" style={{ marginTop: 6 }}><h2><span className="pip" style={{ background: color }} />{title}</h2></div>
      <div className="card" style={{ marginBottom: 18 }}>
        {(arr || []).map((b, i) => (
          <div key={i} className="bb">
            <div style={{ fontWeight: 500 }}>{b.point}</div>
            <div className="row small ink2" style={{ marginTop: 4, gap: 8, alignItems: 'flex-start' }}>
              <span className="grow">{b.evidence}</span><Src s={b.src} links={links} />
            </div>
          </div>
        ))}
      </div>
    </>
  )
  return (
    <>
      {side('Bull case', v.bull, 'var(--up)')}
      {side('Bear case', v.bear, 'var(--down)')}
      {(v.watch_next || []).length > 0 && (
        <>
          <div className="section-h"><h2>Watch next quarter</h2></div>
          <div className="card">{v.watch_next.map((w, i) => <div key={i} className="flag"><span className="fi" style={{ background: 'var(--ink-3)' }} />{w}</div>)}</div>
        </>
      )}
    </>
  )
}

function Numbers({ r }) {
  const N = r.numbers, s = N.series, yrs = N.years
  const last = (arr, k = 6) => arr.slice(-k)
  const FL = { red: 'var(--down)', amber: 'var(--glance)', green: 'var(--up)' }
  return (
    <>
      {N.flags.length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          {N.flags.map((f, i) => (
            <div key={i} className="flag"><span className="fi" style={{ background: FL[f.level] }} /><div><b className="small">{f.area}</b><div>{f.text}</div></div></div>
          ))}
        </div>
      )}
      <div className="tiny muted" style={{ margin: '-4px 2px 14px' }}>Flags are deterministic rules on reported financials; no model is involved.</div>
      <div className="card">
        <div className="chart">
          <h4>Revenue</h4>
          <div className="cap">₹ Cr · 3y CAGR <b className="num">{n(N.growth.revenue['3y'])}%</b> · 5y <b className="num">{n(N.growth.revenue['5y'])}%</b> · PAT 3y <b className="num">{n(N.growth.pat['3y'])}%</b></div>
          <Bars labels={yrs} series={[{ name: 'Revenue', values: s.revenue, color: 'var(--series-1)' }]} />
        </div>
      </div>
      <div className="card">
        <div className="chart">
          <h4>{N.is_financial ? 'Financing margin' : 'Operating margin'}</h4>
          <div className="cap">% of revenue</div>
          <Bars labels={yrs} series={[{ name: 'Margin', values: s.opm, color: 'var(--series-1)' }]} fmt={(v) => `${n(v, 0)}%`} h={100} />
        </div>
      </div>
      {!N.is_financial && (
        <div className="card">
          <div className="chart">
            <h4>Do profits turn into cash?</h4>
            <div className="cap">5y cash from operations ÷ PAT = <b className="num">{N.cash.cfo_to_pat_5y ?? '—'}×</b> · 5y free cash flow <b className="num">{cr(N.cash.fcf_5y_sum)}</b></div>
            <Bars legend labels={last(yrs)} series={[
              { name: 'Cash from ops', values: last(s.cfo), color: 'var(--series-1)' },
              { name: 'PAT', values: last(s.pat), color: 'var(--series-2)' },
            ]} />
          </div>
        </div>
      )}
      {!N.is_financial && s.ccc.some((x) => x != null) && (
        <div className="card">
          <div className="chart">
            <h4>Working-capital cycle</h4>
            <div className="cap">Cash conversion cycle, days · debtor days now <b className="num">{n(last(s.debtor_days, 1)[0], 0)}</b></div>
            <Bars labels={yrs} series={[{ name: 'CCC', values: s.ccc, color: 'var(--series-1)' }]} fmt={(v) => `${n(v, 0)} d`} h={100} />
          </div>
        </div>
      )}
      <div className="kv" style={{ gridTemplateColumns: 'repeat(3,1fr)', marginTop: 14 }}>
        <div><div className="k">Debt / equity</div><div className="v">{N.balance.debt_to_equity ?? '—'}</div></div>
        <div><div className="k">Borrowings</div><div className="v">{n((N.balance.borrowings || 0) / 1000, 1)}k</div></div>
        <div><div className="k">Int. cover</div><div className="v">{N.balance.interest_cover ? `${N.balance.interest_cover}×` : '—'}</div></div>
      </div>
      <div className="section-h" style={{ marginTop: 22 }}><h2>Quarterly</h2><span className="count">₹ Cr</span></div>
      <div className="card card-pad" style={{ paddingTop: 6 }}>
        <table className="rt" style={{ marginTop: 0 }}>
          <thead><tr><th>Qtr</th><th>Revenue</th><th>YoY</th><th>Margin</th><th>PAT YoY</th></tr></thead>
          <tbody>
            {N.quarters.slice(-6).map((q) => (
              <tr key={q.q}><td>{q.q}</td><td>{n(q.revenue, 0)}</td><td><Delta v={q.rev_yoy} d={0} /></td><td>{n(q.opm, 0)}%</td><td><Delta v={q.pat_yoy} d={0} /></td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Business({ r, links }) {
  const ar = r.ar || {}
  const TONE = { confident: 'var(--up)', measured: 'var(--series-1)', cautious: 'var(--glance)', defensive: 'var(--down)' }
  return (
    <>
      <div className="card card-pad">
        <div style={{ fontFamily: 'var(--serif)', fontSize: 17, lineHeight: 1.4 }}>{ar.what_they_do || r.about}</div>
        {ar.segments?.length > 0 && (
          <div style={{ marginTop: 14 }}>
            {ar.segments.map((sg) => (
              <div key={sg.name} style={{ marginTop: 10 }}>
                <div className="row between small"><b>{sg.name}</b><span className="num">{sg.share_pct != null ? `${sg.share_pct}%` : ''}</span></div>
                {sg.share_pct != null && <div className="meter"><span style={{ width: `${Math.min(100, sg.share_pct)}%`, background: 'var(--series-1)' }} /></div>}
                {sg.note && <div className="tiny muted" style={{ marginTop: 3 }}>{sg.note}</div>}
              </div>
            ))}
          </div>
        )}
        {ar.label && <div className="tiny muted" style={{ marginTop: 12 }}>From {ar.label}: read {ar.pages_read} most relevant of {ar.pages_total} pages <Src s="AR" links={links} /></div>}
      </div>
      {r.docs.length > 0 && (
        <>
          <div className="section-h" style={{ marginTop: 22 }}><h2>Management tone, call by call</h2></div>
          <div className="card">
            {[...r.docs].reverse().map((d) => (
              <div key={d.tag} className="flag" style={{ alignItems: 'flex-start' }}>
                <span className="fi" style={{ background: TONE[d.tone] || 'var(--ink-3)' }} />
                <div className="grow">
                  <div className="row between"><b className="small">{d.period || d.label}</b><span className="tiny muted">{d.tone}</span></div>
                  <div className="small ink2">{d.tone_why}</div>
                  {d.pushback?.length > 0 && <div className="tiny muted" style={{ marginTop: 4 }}>Analysts pressed on: {d.pushback.map((p) => `${p.concern} (${p.answer})`).join('; ')}</div>}
                </div>
                <Src s={d.tag} links={links} />
              </div>
            ))}
          </div>
        </>
      )}
      {ar.watch?.length > 0 && (
        <>
          <div className="section-h" style={{ marginTop: 22 }}><h2>In the fine print</h2><span className="count">annual report notes</span></div>
          <div className="card">
            {ar.watch.map((w, i) => (
              <div key={i} className="flag">
                <span className="fi" style={{ background: 'var(--glance)' }} />
                <div className="grow"><b className="small">{w.type.replace(/_/g, ' ')}</b>{w.amount_cr ? <span className="small muted"> · {cr(w.amount_cr)}</span> : ''}<div>{w.text}</div></div>
                <Src s={w.page ? `AR p.${w.page}` : null} links={links} />
              </div>
            ))}
          </div>
        </>
      )}
    </>
  )
}

function Ask({ r, links }) {
  const [q, setQ] = useState('')
  const [hist, setHist] = useState([])
  const [busy, setBusy] = useState(false)
  const voice = useVoice((t) => { setQ(t); go(t) })
  const go = (text) => {
    const qq = (text ?? q).trim()
    if (!qq || busy) return
    setBusy(true)
    api.ask(r.symbol, qq).then((a) => setHist((h) => [{ q: qq, a }, ...h])).catch((e) => setHist((h) => [{ q: qq, a: { answer: e.message } }, ...h])).finally(() => { setBusy(false); setQ('') })
  }
  const SUG = ['What did management guide for next year?', 'What are analysts most worried about?', 'Any comments on pricing or market share?', 'What is the capex plan?']
  const render = (txt) => String(txt).split(/(\[(?:T\d|AR)[^\]]*\])/g).map((p, i) => {
    const m = p.match(/^\[((T\d|AR))\s*p\.?\s*(\d+)\]$/)
    return m && links[m[1]] ? <a key={i} className="src" href={`${links[m[1]]}#page=${m[3]}`} target="_blank" rel="noreferrer">{p.slice(1, -1)}</a> : p
  })
  return (
    <>
      <div className="askbox">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && go()} placeholder={`Ask about ${r.name.split(' ')[0]}'s filings…`} />
        <button className={`mic ${voice.on ? 'on' : ''}`} onClick={voice.start} aria-label="Speak">{Icon.mic}</button>
      </div>
      <div className="chips wrap" style={{ marginTop: 10 }}>{SUG.map((s) => <button key={s} className="chip small" onClick={() => go(s)}>{s}</button>)}</div>
      {busy && <div className="steps"><div className="step"><span className="ic run" /><span className="muted">Searching transcripts and the annual report…</span></div></div>}
      {hist.map((h, i) => (
        <div key={i} className="card qa fadein">
          <div className="card-pad small muted" style={{ paddingBottom: 0 }}>{h.q}</div>
          <div className="qa-a">{render(h.a.answer)}</div>
          {h.a.sources?.length > 0 && <div className="tiny muted" style={{ padding: '0 14px 12px' }}>Retrieved {h.a.sources.length} pages by keyword search, answered by the fast model · confidence {h.a.confidence}</div>}
        </div>
      ))}
      <div className="tiny muted" style={{ marginTop: 14 }}>Answers come only from this company's own transcripts and annual report. No news, broker notes or model memory.</div>
    </>
  )
}

function Dossier({ r, onRefresh }) {
  const [tab, setTab] = useState('promises')
  const v = deepClean(r.verdict || {})
  const links = Object.fromEntries((r.docs || []).map((d) => [d.tag, d.url]))
  if (r.ar?.url) links.AR = r.ar.url
  const N = r.numbers
  const hasV = v && (v.promises || []).length > 0
  const TABS = [['promises', 'Said vs done'], ['numbers', 'Numbers'], ['case', 'Bull / bear'], ['business', 'Business'], ['ask', 'Ask']]
    .filter(([k]) => hasV || !['promises', 'case'].includes(k))
  const t = TABS.find(([k]) => k === tab) ? tab : TABS[0][0]
  return (
    <div className="fadein">
      <div className="dossier-h">
        <div className="eyebrow">{r.symbol} · research dossier</div>
        <div className="dossier-name">{r.name}</div>
        <div className="kv">
          <div><div className="k">Mcap</div><div className="v">{n((N.snapshot.market_cap_cr || 0) / 1000, 0)}k</div></div>
          <div><div className="k">P/E</div><div className="v">{n(N.snapshot.pe, 1)}</div></div>
          <div><div className="k">{N.is_financial ? 'ROE' : 'ROCE'}</div><div className="v">{n(N.is_financial ? N.snapshot.roe : N.snapshot.roce, 0)}%</div></div>
          <div><div className="k">Rev 3y</div><div className="v">{n(N.growth.revenue['3y'], 0)}%</div></div>
        </div>
        {v.tldr && <div className="tldr">{v.tldr}</div>}
        {r.note && <div className="card card-pad small" style={{ marginTop: 14 }}>{r.note}</div>}
      </div>
      <div className="seg">{TABS.map(([k, l]) => <button key={k} className={t === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
      {t === 'promises' && <Promises v={v} links={links} />}
      {t === 'numbers' && <Numbers r={r} />}
      {t === 'case' && <Case v={v} links={links} />}
      {t === 'business' && <Business r={r} links={links} />}
      {t === 'ask' && <Ask r={r} links={links} />}
      <div className="cost">
        <div className="row between"><b style={{ fontFamily: 'var(--sans)' }}>How this was made</b><button className="link tiny" onClick={onRefresh}>Re-run</button></div>
        <div className="row wrap" style={{ marginTop: 6, gap: 4 }}>
          <span>Sources:</span>
          {(r.docs || []).map((d) => <a key={d.tag} className="src" href={d.url} target="_blank" rel="noreferrer">{d.tag} {d.period || d.label}</a>)}
          {r.ar && <a className="src" href={r.ar.url} target="_blank" rel="noreferrer">AR {r.ar.fiscal_year || ''}</a>}
          <span>+ exchange-reported financials.</span>
        </div>
        {r.cost && (
          <div style={{ marginTop: 6 }}>
            <b>{r.cost.calls}</b> model calls ({Object.entries(r.cost.by_tier || {}).map(([k, x]) => `${x.calls}× ${k} tier · ${x.model}`).join(', ')}) · <b>{n((r.cost.tokens_build ?? r.cost.tokens) / 1000, 0)}k</b> tokens · <b>${r.cost.usd_build ?? r.cost.usd}</b> at paid rates, $0 on the free tier{r.elapsed_s && r.cost.cached < r.cost.calls ? ` · built in ${r.elapsed_s}s` : ''}
            {r.cost.cached > 0 && <div className="muted">{r.cost.cached} of {r.cost.calls} steps were reused from cache: documents are read once, ever.</div>}
          </div>
        )}
        {r.generated && <div className="muted" style={{ marginTop: 4 }}>Generated {r.generated}</div>}
      </div>
    </div>
  )
}

export default function Research({ symbol, setSymbol, demo }) {
  const [q, setQ] = useState('')
  const [sug, setSug] = useState([])
  const [job, setJob] = useState(null)
  const [recent, setRecent] = useState(() => store.get('recent', []))
  const timer = useRef()
  const voice = useVoice((t) => { setQ(t); api.search(t).then((x) => x[0] && pick(x[0].symbol)) })

  useEffect(() => {
    if (!q || q.length < 2) return setSug([])
    const id = setTimeout(() => api.search(q).then(setSug).catch(() => {}), 220)
    return () => clearTimeout(id)
  }, [q])

  const poll = (s) => {
    clearTimeout(timer.current)
    api.researchStatus(s).then((st) => {
      setJob(st)
      if (st.status === 'running') timer.current = setTimeout(() => poll(s), 1200)
    }).catch(() => (timer.current = setTimeout(() => poll(s), 2000)))
  }

  const start = (s, force) => {
    setJob({ status: 'running', steps: [], symbol: s })
    api.research(s, force).then((st) => { setJob(st); if (st.status === 'running') poll(s) }).catch((e) => setJob({ status: 'error', error: e.message }))
  }

  useEffect(() => {
    if (symbol) start(symbol)
    return () => clearTimeout(timer.current)
  }, [symbol])

  const pick = (s) => {
    setQ(''); setSug([])
    const r = [s, ...recent.filter((x) => x !== s)].slice(0, 6)
    setRecent(r); store.set('recent', r)
    if (s === symbol) start(s); else setSymbol(s)
  }

  const res = job?.result
  return (
    <div className="page">
      {!symbol && (
        <div className="hero">
          <div className="eyebrow">Research · any NSE company</div>
          <h1 className="headline">What did management <em>promise</em>, and did they deliver?</h1>
          <div className="sub">FINN reads the last four earnings calls and the annual report, then checks every guidance statement against the reported numbers.</div>
        </div>
      )}
      <div style={{ position: 'relative', marginTop: symbol ? 12 : 16 }}>
        <div className="askbox">
          <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && sug[0] && pick(sug[0].symbol)} placeholder="Company name or ticker…" />
          <button className={`mic ${voice.on ? 'on' : ''}`} onClick={voice.start} aria-label="Speak a company">{Icon.mic}</button>
        </div>
        {sug.length > 0 && (
          <div className="suggest">
            {sug.map((x) => <button key={x.symbol} onClick={() => pick(x.symbol)}><span>{x.name}</span><span className="sym">{x.symbol}</span></button>)}
          </div>
        )}
      </div>
      {!symbol && (
        <>
          <div className="section"><div className="section-h"><h2>Try it on</h2><span className="count">outside your portfolio</span></div>
            <div className="chips wrap">{(demo?.research || []).map((s) => <button key={s} className="chip" onClick={() => pick(s)}>{s}</button>)}</div>
          </div>
          <div className="section"><div className="section-h"><h2>Your holdings</h2></div>
            <div className="chips wrap">{(demo?.portfolio || []).map((s) => <button key={s} className="chip ghost small" onClick={() => pick(s)}>{s}</button>)}</div>
          </div>
          {recent.length > 0 && (
            <div className="section"><div className="section-h"><h2>Recent</h2></div>
              <div className="chips wrap">{recent.map((s) => <button key={s} className="chip ghost small" onClick={() => pick(s)}>{s}</button>)}</div>
            </div>
          )}
        </>
      )}
      {symbol && job && job.status === 'running' && (
        <div className="section">
          <div className="dossier-name">{symbol}</div>
          <div className="sub">Reading primary documents. Usually 30–90 seconds the first time, instant after that.</div>
          <Steps steps={job.steps || []} running />
        </div>
      )}
      {symbol && job?.status === 'error' && <div className="empty">Couldn't research {symbol}: {job.error}</div>}
      {symbol && res && job.status === 'done' && <div style={{ marginTop: 10 }}><Dossier r={res} onRefresh={() => start(symbol, true)} /></div>}
    </div>
  )
}
