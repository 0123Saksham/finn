import { useEffect, useState } from 'react'
import { CATS, DEFAULT_RULES, api } from './api'
import { Delta, n } from './ui'

export default function Rules({ rules, setRules, notify, setNotify }) {
  const [draft, setDraft] = useState(rules)
  const [pv, setPv] = useState(null)

  useEffect(() => {
    const id = setTimeout(() => {
      setRules(draft)
      api.preview({ ...draft, days: 30 }).then(setPv).catch(() => {})
    }, 250)
    return () => clearTimeout(id)
  }, [draft])

  const toggle = (c) => setDraft((d) => ({ ...d, categories: d.categories.includes(c) ? d.categories.filter((x) => x !== c) : [...d.categories, c] }))

  const askNotify = async () => {
    if (!('Notification' in window)) return alert('This browser does not support notifications.')
    if (notify) return setNotify(false)
    const p = await Notification.requestPermission()
    setNotify(p === 'granted')
  }

  const perDay = pv ? pv.total / 30 : 0
  const verdict = !pv ? '' : perDay > 3 ? 'That is noise. Tighten something.' : perDay > 1 ? 'Busy, but manageable.' : perDay < 0.15 ? 'Very quiet. You might miss things.' : 'A sensible signal-to-noise ratio.'

  return (
    <div className="page">
      <div className="hero">
        <div className="eyebrow">Alert rules</div>
        <h1 className="headline">You decide what <em>unusual</em> means.</h1>
        <div className="sub">FINN checks every close and every filing against these lines. Drag a slider to see how often it would have pinged you over the last 30 days.</div>
      </div>

      <div className="card preview" style={{ marginTop: 16 }}>
        {pv ? (
          <>
            <div className="big">≈ <span className="num">{n(pv.per_week, 0)}</span> pings a week</div>
            <div className="small ink2" style={{ marginTop: 4 }}>{pv.total} in 30 days: {pv.by_type.price} price · {pv.by_type.volume} volume · {pv.by_type.filing} filings. {verdict}</div>
            <div className="funnel-bar" style={{ marginTop: 12 }}>
              <span style={{ flex: pv.by_type.price || 0.001, background: 'var(--series-1)' }} />
              <span style={{ flex: pv.by_type.volume || 0.001, background: 'var(--series-2)' }} />
              <span style={{ flex: pv.by_type.filing || 0.001, background: 'var(--ink-3)' }} />
            </div>
            <div className="funnel-legend">
              <span><span className="sw" style={{ background: 'var(--series-1)' }} />Price</span>
              <span><span className="sw" style={{ background: 'var(--series-2)' }} />Volume</span>
              <span><span className="sw" style={{ background: 'var(--ink-3)' }} />Filing</span>
            </div>
            {pv.sample?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                {pv.sample.slice(0, 4).map((a, i) => (
                  <div key={i} className="routine-item">
                    <span className="sym" style={{ minWidth: 80 }}>{a.symbol}</span>
                    <span className="grow">{a.type === 'price' ? <Delta v={a.value} /> : a.type === 'volume' ? `${a.value}× volume` : a.label}</span>
                    <span className="tiny muted">{new Date(a.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : <div className="skeleton" style={{ height: 80 }} />}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="rule">
          <div className="rule-h"><span>Daily price move beyond</span><span className="rule-v">±{draft.price_move_pct}%</span></div>
          <input type="range" min="1" max="12" step="0.5" value={draft.price_move_pct} onChange={(e) => setDraft({ ...draft, price_move_pct: +e.target.value })} />
        </div>
        <div className="rule">
          <div className="rule-h"><span>Volume vs 20-day average</span><span className="rule-v">{draft.volume_multiple}×</span></div>
          <input type="range" min="1.2" max="6" step="0.1" value={draft.volume_multiple} onChange={(e) => setDraft({ ...draft, volume_multiple: +e.target.value })} />
        </div>
        <div className="rule">
          <div className="rule-h"><span>Material filings that alert me</span><span className="small muted">{draft.categories.length} on</span></div>
          <div className="chips wrap" style={{ marginTop: 10 }}>
            {CATS.map(([k, l]) => <button key={k} className={`chip small ${draft.categories.includes(k) ? 'on' : 'ghost'}`} onClick={() => toggle(k)}>{l}</button>)}
          </div>
          <div className="tiny muted" style={{ marginTop: 8 }}>Only filings FINN scores as material fire an alert. A routine credit-rating reaffirmation won't.</div>
        </div>
        <div className="rule row between">
          <div>
            <div>Notify me on this device</div>
            <div className="tiny muted">When something new clears your bar while FINN is open or installed</div>
          </div>
          <button className={`toggle ${notify ? 'on' : ''}`} onClick={askNotify} aria-label="Toggle notifications" />
        </div>
      </div>
      <button className="chip ghost" style={{ marginTop: 14 }} onClick={() => setDraft(DEFAULT_RULES)}>Reset to defaults</button>
    </div>
  )
}
