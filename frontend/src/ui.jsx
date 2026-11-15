import { useState } from 'react'

export const cr = (v, d = 0) =>
  v == null ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: d })} Cr`
export const n = (v, d = 1) => (v == null ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: d }))
export const pct = (v, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`)
export const cls = (v) => (v == null ? 'muted' : v > 0 ? 'up' : v < 0 ? 'down' : 'muted')

export function ago(ts) {
  if (!ts) return ''
  const d = (Date.now() - new Date(ts).getTime()) / 1000
  if (d < 3600) return `${Math.max(1, Math.round(d / 60))}m ago`
  if (d < 86400) return `${Math.round(d / 3600)}h ago`
  if (d < 86400 * 7) return `${Math.round(d / 86400)}d ago`
  return new Date(ts).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

export function Delta({ v, d = 1, suffix }) {
  return <span className={`num ${cls(v)}`}>{pct(v, d)}{suffix}</span>
}

export function Spark({ data, w = 70, h = 26, color }) {
  if (!data || data.length < 2) return <svg width={w} height={h} />
  const min = Math.min(...data), max = Math.max(...data)
  const x = (i) => (i / (data.length - 1)) * (w - 4) + 2
  const y = (v) => h - 3 - ((v - min) / (max - min || 1)) * (h - 6)
  const up = data[data.length - 1] >= data[0]
  const c = color || (up ? 'var(--up)' : 'var(--down)')
  const d = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  return (
    <svg width={w} height={h} role="img" aria-label={`60-day trend ${up ? 'up' : 'down'}`}>
      <path d={d} fill="none" stroke={c} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(data.length - 1)} cy={y(data[data.length - 1])} r="2.4" fill={c} />
    </svg>
  )
}

/** Single- or two-series bar chart with per-bar hover tooltip. Values in ₹ Cr or %. */
export function Bars({ labels, series, h = 120, fmt = (v) => n(v, 0), legend }) {
  const [hover, setHover] = useState(null)
  const all = series.flatMap((s) => s.values).filter((v) => v != null)
  if (!all.length) return <div className="muted small">No data</div>
  const max = Math.max(0, ...all), min = Math.min(0, ...all)
  const W = 320, pad = 4, bw = (W - pad * 2) / labels.length
  const inner = bw - 6
  const sw = series.length > 1 ? (inner - 2) / series.length : inner
  const y = (v) => 18 + (1 - (v - min) / (max - min || 1)) * (h - 36)
  const zero = y(0)
  return (
    <div style={{ position: 'relative' }}>
      {legend && series.length > 1 && (
        <div className="row small ink2" style={{ gap: 14, marginBottom: 6 }}>
          {series.map((s) => (
            <span key={s.name}><span className="sw" style={{ background: s.color }} />{s.name}</span>
          ))}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${h}`} width="100%" height={h} role="img" aria-label={series.map((s) => s.name).join(' vs ')}>
        <line x1="0" x2={W} y1={zero} y2={zero} stroke="var(--line)" strokeWidth="1" />
        {labels.map((lab, i) =>
          series.map((s, k) => {
            const v = s.values[i]
            if (v == null) return null
            const x0 = pad + i * bw + 3 + k * (sw + 2)
            const top = Math.min(y(v), zero), ht = Math.max(1.5, Math.abs(y(v) - zero))
            return (
              <rect key={`${i}-${k}`} x={x0} y={top} width={sw} height={ht} rx={Math.min(4, sw / 2)}
                fill={s.color} opacity={hover == null || hover === i ? 1 : 0.45} />
            )
          })
        )}
        {series.length === 1 && (() => {
          const i = labels.length - 1, v = series[0].values[i]
          if (v == null) return null
          return <text x={pad + i * bw + bw / 2} y={Math.min(y(v), zero) - 4} textAnchor="middle" fontSize="10" fontWeight="600" fill="var(--ink)" fontFamily="var(--mono)">{fmt(v)}</text>
        })()}
        {labels.map((lab, i) => (
          <text key={lab} x={pad + i * bw + bw / 2} y={h - 4} textAnchor="middle" fontSize="9.5" fill="var(--ink-3)" fontFamily="var(--mono)">
            {labels.length > 8 && i % 2 && i !== labels.length - 1 ? '' : lab}
          </text>
        ))}
        {labels.map((lab, i) => (
          <rect key={`h${i}`} x={pad + i * bw} y="0" width={bw} height={h} fill="transparent"
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onTouchStart={() => setHover(i)} />
        ))}
      </svg>
      {hover != null && (
        <div className="tip" style={{ left: `${((pad + hover * bw + bw / 2) / W) * 100}%`, top: 18 }}>
          {labels[hover]} · {series.map((s) => `${series.length > 1 ? s.name + ' ' : ''}${fmt(s.values[hover])}`).join(' · ')}
        </div>
      )}
    </div>
  )
}

export function Sheet({ onClose, children }) {
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog">
        <div className="grabber" />
        {children}
      </div>
    </>
  )
}

export const Icon = {
  brief: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 6h16M4 12h10M4 18h6" /><circle cx="18" cy="16" r="3" /></svg>
  ),
  book: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 17l5-5 4 4 8-8" /><path d="M15 8h5v5" /></svg>
  ),
  ask: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg>
  ),
  rules: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 7h9M17 7h3M4 17h3M11 17h9" /><circle cx="15" cy="7" r="2" /><circle cx="9" cy="17" r="2" /></svg>
  ),
  mic: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" /></svg>
  ),
  play: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z" /></svg>
  ),
  stop: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
  ),
  ext: (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" /></svg>
  ),
  arrow: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
  ),
  check: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
  ),
}
