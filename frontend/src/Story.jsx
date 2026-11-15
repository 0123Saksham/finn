import { useState } from 'react'
import { Delta, Icon, ago, cr, n } from './ui'

export const qlabel = (e) => {
  const p = e?.check?.period
  if (p) {
    const [m, y] = p.split(' '); const q = { Jun: 1, Sep: 2, Dec: 3, Mar: 4 }[m]
    if (q) return `Q${q} FY${String(q === 4 ? +y : +y + 1).slice(-2)}`
  }
  return (e?.labels?.current || 'Quarter').split('(')[0].replace(/quarter ended/i, 'Qtr to').trim()
}
const short = (name = '') => name.replace(/\b(Limited|Ltd\.?|Industries|Company|Enterprises|Technologies|\(India\))\b/g, '').replace(/\s+/g, ' ').trim()

function Results({ e }) {
  const cur = qlabel(e)
  return (
    <>
      <table className="rt">
        <thead>
          <tr><th>₹ Cr</th><th>{cur}</th><th>QoQ</th><th>YoY</th></tr>
        </thead>
        <tbody>
          {e.rows.map((r) => (
            <tr key={r.metric}>
              <td>{r.metric}</td>
              <td>{n(r.value, 0)}</td>
              <td><Delta v={r.qoq} d={0} /></td>
              <td><Delta v={r.yoy} d={0} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {e.margin && (
        <div className="small ink2" style={{ marginTop: 8 }}>
          EBITDA margin <b className="num">{e.margin.now}%</b>
          {e.margin.yoy_q != null && <> vs <span className="num">{e.margin.yoy_q}%</span> a year ago</>}
        </div>
      )}
      {e.lender && <div className="small muted" style={{ marginTop: 8 }}>Lender: EBITDA isn't meaningful, so pre-provision operating profit is shown instead.</div>}
      {e.check && (
        <div className={`verify ${e.check.match ? '' : 'warn'}`}>
          {e.check.match ? Icon.check : '⚠'}
          {e.check.match
            ? `Revenue cross-checked against exchange-reported ${e.check.period} figure`
            : `Revenue differs from exchange-reported ${cr(e.check.revenue_ref)} — check basis`}
        </div>
      )}
    </>
  )
}

const ACT = { appointed: 'up', resigned: 'down', ceased: 'down', retired: 'amber', superannuated: 'amber', reappointed: 'muted', redesignated: 'muted' }

function People({ e }) {
  return (e.changes || []).slice(0, 2).map((c, i) => (
    <div className="person" key={i}>
      <div className="avatar">{(c.person || '?').replace(/^(Mr|Ms|Mrs|Dr|Shri|Smt)\.?\s+/i, '').split(' ').map((w) => w[0]).slice(0, 2).join('')}</div>
      <div className="grow">
        <div className="row between">
          <span className="person-name">{c.person}</span>
          <span className={`act ${ACT[c.action] || 'muted'}`}>{c.action}</span>
        </div>
        <div className="person-role">{c.role}{c.effective ? ` · from ${c.effective}` : ''}</div>
        {c.bio?.summary && <div className="person-bio">{c.bio.summary}</div>}
        {c.bio?.prior?.length > 0 && <div className="prior">{c.bio.prior.slice(0, 4).map((p) => <span key={p}>{p}</span>)}</div>}
        <div className="row small" style={{ marginTop: 8, gap: 12 }}>
          {c.bio?.education && <span className="muted">{c.bio.education}</span>}
          {c.linkedin && <a className="link" href={c.linkedin} target="_blank" rel="noreferrer">LinkedIn {Icon.ext}</a>}
        </div>
      </div>
    </div>
  ))
}

function Scale({ s }) {
  if (!s) return null
  return <span className="scale">{cr(s.amount_cr, 0)} = {s.pct < 0.1 ? '<0.1' : s.pct}% {s.of}</span>
}

export function StoryCard({ s, onResearch, isNew }) {
  const [open, setOpen] = useState(false)
  const e = s.enrich || {}
  const title =
    e.kind === 'results' ? `${short(s.name)}: ${qlabel(e)} results`
      : e.kind === 'people' && e.headline ? e.headline
        : s.oneliner || s.title
  return (
    <article className="card fadein">
      <div className="card-pad">
        <div className="story-top">
          <span className="sym">{s.symbol}</span>
          <span className={`tag ${s.tier === 'matters' ? 'hot' : 'warm'}`}>{s.label}</span>
          <span>{ago(s.ts)}</span>
          {isNew && <span className="new">New</span>}
          <span className="grow" />
          {s.px?.chg_pct != null && <Delta v={s.px.chg_pct} />}
        </div>
        <h3 className="story-title">{title}</h3>
        {e.kind === 'results' && e.takeaway && <div className="story-line">{e.takeaway}</div>}
        {e.kind === 'results' && <Results e={e} />}
        {e.kind === 'people' && <People e={e} />}
        {e.kind === 'line' && <Scale s={e.scale} />}
        {!s.enrich && s.title !== title && <div className="story-line">{s.title}</div>}
        {s.related?.length > 0 && (
          <button className="small muted" style={{ marginTop: 10 }} onClick={() => setOpen(!open)}>
            {open ? '−' : '+'} {s.related.length} related filing{s.related.length > 1 ? 's' : ''} grouped into this story
          </button>
        )}
        {open && s.related.map((r) => (
          <a key={r.url} className="routine-item" href={r.url} target="_blank" rel="noreferrer">
            <span className="tag">{r.label}</span><span className="grow">{r.title}</span>
          </a>
        ))}
        <div className="tiny muted" style={{ marginTop: 10 }}>{s.weight}% of your book{e.route ? ` · read by ${e.route.replace('fast · ', 'fast model, ')}` : ''}</div>
      </div>
      <div className="story-foot">
        <a className="link" href={s.url} target="_blank" rel="noreferrer">Source filing {Icon.ext}</a>
        <button className="link" onClick={() => onResearch(s.symbol)}>Research {s.symbol} {Icon.arrow}</button>
      </div>
    </article>
  )
}

export function GlanceRow({ s, onResearch, onMute, isNew }) {
  const [open, setOpen] = useState(false)
  const e = s.enrich || {}
  return (
    <div className="glance-row">
      <button style={{ width: '100%', textAlign: 'left' }} onClick={() => setOpen(!open)}>
        <div className="story-top">
          <span className="sym">{s.symbol}</span>
          <span className="tag">{s.label}</span>
          <span>{ago(s.ts)}</span>
          {isNew && <span className="new">New</span>}
          <span className="grow" />
          {s.px?.chg_pct != null && <Delta v={s.px.chg_pct} />}
        </div>
        <div className="t">{e.headline || s.oneliner || s.title}</div>
        {e.kind === 'line' && <Scale s={e.scale} />}
      </button>
      {open && (
        <div className="fadein" style={{ marginTop: 10 }}>
          {e.kind === 'people' && <People e={e} />}
          {(s.oneliner || e.headline) && <div className="small muted" style={{ marginTop: 8 }}>Filed as: {s.title}</div>}
          <div className="row" style={{ marginTop: 10, gap: 14 }}>
            <a className="link small" href={s.url} target="_blank" rel="noreferrer">Filing {Icon.ext}</a>
            <button className="link small" onClick={() => onResearch(s.symbol)}>Dig in {Icon.arrow}</button>
            <span className="grow" />
            <button className="link small muted" onClick={() => onMute(s.category, s.label)}>Hide {s.label.toLowerCase()} filings</button>
          </div>
        </div>
      )}
    </div>
  )
}
