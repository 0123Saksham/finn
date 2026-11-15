import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { GlanceRow, StoryCard } from './Story'
import { Delta, Icon, ago, n } from './ui'

const WINDOWS = [
  ['since', 'Since last visit'], [24, '24h'], [72, '3 days'], [168, 'Week'], [720, 'Month'],
]

function greet() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

const words = ['Nothing', 'One thing', 'Two things', 'Three things', 'Four things', 'Five things', 'Six things', 'Seven things']

function script(d) {
  const m = d.stories.filter((s) => s.tier === 'matters')
  const parts = [`${greet()}. ${m.length ? `${words[m.length] || m.length + ' things'} need${m.length === 1 ? 's' : ''} your attention.` : 'Nothing in your portfolio needs you right now.'}`]
  m.forEach((s, i) => {
    const e = s.enrich || {}
    let line = `${i + 1}. ${s.name}. `
    if (e.kind === 'results') {
      const r = Object.fromEntries(e.rows.map((x) => [x.metric, x]))
      line += `Results: revenue ${r.Revenue?.yoy >= 0 ? 'up' : 'down'} ${Math.abs(Math.round(r.Revenue?.yoy || 0))} percent year on year; profit after tax ${r.PAT?.yoy >= 0 ? 'up' : 'down'} ${Math.abs(Math.round(r.PAT?.yoy || 0))} percent.`
    } else line += (e.headline || s.oneliner || s.title) + '.'
    parts.push(line)
  })
  const mv = d.alerts.filter((a) => a.type === 'price').slice(0, 2)
  if (mv.length) parts.push('Unusual moves: ' + mv.map((a) => `${a.symbol.split('').join(' ')} ${a.value > 0 ? 'up' : 'down'} ${Math.abs(a.value).toFixed(1)} percent`).join(', ') + '.')
  parts.push(`${d.counts.routine} routine filings were filed away.`)
  return parts.join(' ')
}

export default function Brief({ rules, muted, onMute, onUnmute, lastVisit, onResearch, onAlertCount }) {
  const [win, setWin] = useState(lastVisit ? 'since' : 24)
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [showRoutine, setShowRoutine] = useState(false)
  const [speaking, setSpeaking] = useState(false)

  const [picked, setPicked] = useState(false)
  const [widened, setWidened] = useState(null)

  useEffect(() => {
    setD(null); setErr(null)
    const p = { ...rules, muted }
    if (win === 'since' && lastVisit) p.since = lastVisit
    else p.hours = win === 'since' ? 24 : win
    api.digest(p).then((x) => {
      // Weekends and holidays make a 24h window empty. Unless the user chose the window,
      // widen it until there's something worth reading, and say so.
      if (!picked && x.counts.matters === 0 && (p.hours || 24) < 168) {
        const next = (p.hours || 24) < 72 ? 72 : 168
        setWidened(win === 'since' ? 'since your last visit' : `the last ${win === 24 ? '24 hours' : '3 days'}`)
        setWin(next)
        return
      }
      setD(x); onAlertCount?.(x.counts.matters)
    }).catch((e) => setErr(e.message))
  }, [win, rules, muted, lastVisit])

  const choose = (k) => { setPicked(true); setWidened(null); setWin(k) }

  useEffect(() => () => window.speechSynthesis?.cancel(), [])

  const groups = useMemo(() => {
    if (!d) return {}
    return {
      matters: d.stories.filter((s) => s.tier === 'matters'),
      glance: d.stories.filter((s) => s.tier === 'glance'),
      routine: d.stories.filter((s) => s.tier === 'routine'),
    }
  }, [d])

  const listen = () => {
    if (!window.speechSynthesis) return
    if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return }
    const u = new SpeechSynthesisUtterance(script(d))
    u.lang = 'en-IN'; u.rate = 1.04
    u.onend = () => setSpeaking(false)
    window.speechSynthesis.speak(u); setSpeaking(true)
  }

  const moves = (d?.alerts || []).filter((a) => a.type !== 'filing')
  const total = d ? d.counts.matters + d.counts.glance + d.counts.routine : 0

  return (
    <div className="page">
      <div className="hero">
        <div className="eyebrow">{new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}</div>
        {d ? (
          <h1 className="headline">
            {greet()}. {groups.matters.length
              ? <><em>{words[groups.matters.length] || groups.matters.length + ' things'}</em> need{groups.matters.length === 1 ? 's' : ''} you.</>
              : <>Nothing needs you <em>right now</em>.</>}
          </h1>
        ) : <div className="skeleton" style={{ height: 70, margin: '8px 0' }} />}
        {d && (
          <div className="sub">
            {d.counts.filings} filings across 18 holdings, grouped into {total} stories. {d.counts.routine} routine ones are folded away.
            {widened && <div className="small" style={{ marginTop: 6 }}><span className="tag warm">Quiet</span> Nothing material in {widened}, so the window was widened.</div>}
          </div>
        )}
      </div>

      <div className="chips" style={{ marginTop: 12 }}>
        {WINDOWS.filter(([k]) => k !== 'since' || lastVisit).map(([k, label]) => (
          <button key={k} className={`chip ${win === k ? 'on' : ''}`} onClick={() => choose(k)}>{label}</button>
        ))}
      </div>

      {d && total > 0 && (
        <div className="funnel">
          <div className="funnel-bar" aria-hidden>
            <span style={{ flex: groups.matters.length || 0.0001, background: 'var(--accent)' }} />
            <span style={{ flex: groups.glance.length || 0.0001, background: 'var(--glance)' }} />
            <span style={{ flex: groups.routine.length || 0.0001, background: 'var(--line)' }} />
          </div>
          <div className="funnel-legend">
            <span><span className="sw" style={{ background: 'var(--accent)' }} />Matters <b>{groups.matters.length}</b></span>
            <span><span className="sw" style={{ background: 'var(--glance)' }} />Glance <b>{groups.glance.length}</b></span>
            <span><span className="sw" style={{ background: 'var(--line)' }} />Routine <b>{groups.routine.length}</b></span>
            <span className="grow" />
            <button className="link" onClick={listen}>{speaking ? Icon.stop : Icon.play} {speaking ? 'Stop' : 'Listen · 40s'}</button>
          </div>
        </div>
      )}

      {err && <div className="empty">Couldn't load the brief. {err}</div>}

      {moves.length > 0 && (
        <section className="section">
          <div className="section-h">
            <h2>Unusual moves</h2>
            <span className="count">±{rules.price_move_pct}% · {rules.volume_multiple}× vol</span>
          </div>
          <div className="alerts">
            {moves.slice(0, 12).map((a, i) => (
              <button key={i} className="alert" onClick={() => onResearch(a.symbol, 'company')}>
                <div className="row between"><span className="sym">{a.symbol}</span><span className="k">{a.type === 'price' ? 'Price' : 'Volume'}</span></div>
                <div className={`v ${a.type === 'price' ? (a.value > 0 ? 'up' : 'down') : ''}`}>
                  {a.type === 'price' ? <Delta v={a.value} /> : <span className="num">{n(a.value, 1)}×</span>}
                </div>
                <div className="m">
                  {a.type === 'volume' ? <>normal volume · price <Delta v={a.chg_pct} /></> : `${n(a.value > 0 ? a.value : -a.value, 1)}% beyond your ±${a.threshold}% line`}
                  <br />
                  <span className="muted">{new Date(a.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}{a.explained_by_filing ? ' · filing the same day' : ' · no filing explains it'}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      {d && groups.matters.length > 0 && (
        <section className="section">
          <div className="section-h"><h2><span className="pip" style={{ background: 'var(--accent)' }} />Matters</h2><span className="count">{groups.matters.length}</span></div>
          {groups.matters.map((s) => <StoryCard key={s.id} s={s} onResearch={onResearch} />)}
        </section>
      )}

      {d && groups.glance.length > 0 && (
        <section className="section">
          <div className="section-h"><h2><span className="pip" style={{ background: 'var(--glance)' }} />Worth a glance</h2><span className="count">{groups.glance.length}</span></div>
          <div className="card">{groups.glance.map((s) => <GlanceRow key={s.id} s={s} onResearch={onResearch} onMute={onMute} />)}</div>
        </section>
      )}

      {d && groups.routine.length > 0 && (
        <section className="section">
          <div className="section-h"><h2><span className="pip" style={{ background: 'var(--line)' }} />Filed away</h2><span className="count">{groups.routine.length}</span></div>
          <div className="routine-sum">
            {Object.entries(d.routine_breakdown).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <span key={k} className="chip small ghost">{k} <b className="num">{v}</b></span>
            ))}
            <button className="chip small" onClick={() => setShowRoutine(!showRoutine)}>{showRoutine ? 'Hide' : 'Show all'}</button>
          </div>
          {showRoutine && (
            <div className="routine-list fadein">
              {groups.routine.map((s) => (
                <a key={s.id} className="routine-item" href={s.url} target="_blank" rel="noreferrer">
                  <span className="sym" style={{ minWidth: 76 }}>{s.symbol}</span>
                  <span className="grow">{s.oneliner || s.title}</span>
                  <span className="tiny muted">{ago(s.ts)}</span>
                </a>
              ))}
            </div>
          )}
        </section>
      )}

      {muted.length > 0 && (
        <div className="small muted" style={{ marginTop: 18 }}>
          Hidden by you: {muted.map((m) => <button key={m} className="chip small ghost" style={{ marginLeft: 4 }} onClick={() => onUnmute(m)}>{m} ×</button>)}
        </div>
      )}

      {d && total === 0 && (
        <div className="empty">
          No filings from your holdings in this window.
          <div style={{ marginTop: 12 }}><button className="chip" onClick={() => choose(720)}>Show the past month</button></div>
        </div>
      )}
      {d?.refreshed && <div className="tiny muted" style={{ marginTop: 22, textAlign: 'center' }}>Feeds checked {ago(d.refreshed)} · BSE filings via Screener + NSE RSS · EOD prices</div>}
    </div>
  )
}
