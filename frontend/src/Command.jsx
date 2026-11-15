import { useEffect, useRef, useState } from 'react'
import { useVoice } from './Research'
import { Icon, Sheet } from './ui'

const EXAMPLES = [
  'What matters this week?',
  'What happened at HAL?',
  'Is Infosys management credible?',
  'What did Infosys say about margins?',
  'Ping me if anything moves 3%',
  'Research Pidilite',
]

const post = (text) =>
  fetch('/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }).then((r) => r.json())

/** One box for everything: type or speak, FINN works out where to take you. */
export default function Command({ onClose, act, autoVoice }) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)
  const input = useRef()
  const voice = useVoice((t) => { setQ(t); go(t) })

  useEffect(() => { if (autoVoice) voice.start(); else input.current?.focus() }, [])

  const go = (text) => {
    const t = (text ?? q).trim()
    if (!t || busy) return
    setBusy(true); setRes(null)
    post(t).then((r) => {
      setRes(r)
      if (r.intent === 'ask' && r.answer) return
      if (r.intent === 'error') return
      setTimeout(() => act(r), r.intent === 'rules' ? 900 : 150)
    }).catch((e) => setRes({ intent: 'error', message: e.message })).finally(() => setBusy(false))
  }

  const cite = (txt, links = {}) => String(txt).split(/(\[(?:T\d|AR)[^\]]*\])/g).map((p, i) => {
    const m = p.match(/^\[(T\d|AR)\s*p\.?\s*(\d+)?/)
    if (!m) return p
    return links[m[1]] ? <a key={i} className="src" href={`${links[m[1]]}${m[2] ? '#page=' + m[2] : ''}`} target="_blank" rel="noreferrer">{p.slice(1, -1)}</a> : <span key={i} className="src">{p.slice(1, -1)}</span>
  })

  return (
    <Sheet onClose={onClose}>
      <div className="eyebrow">Ask FINN</div>
      <div className="headline" style={{ fontSize: 24, marginTop: 4 }}>Say what you need. FINN takes you there.</div>
      <div className="askbox" style={{ marginTop: 14 }}>
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && go()} placeholder="Ask anything about your portfolio…" />
        <button className={`mic ${voice.on ? 'on' : ''}`} onClick={voice.start} aria-label="Speak">{Icon.mic}</button>
      </div>
      {!res && !busy && (
        <div className="chips wrap" style={{ marginTop: 12 }}>
          {EXAMPLES.map((e) => <button key={e} className="chip small" onClick={() => { setQ(e); go(e) }}>{e}</button>)}
        </div>
      )}
      {busy && <div className="steps"><div className="step"><span className="ic run" /><span className="muted">Working out what you mean…</span></div></div>}
      {res?.intent === 'rules' && <div className="card card-pad fadein" style={{ marginTop: 14 }}><b>Done.</b> Alerts now fire at {res.rules.price_move_pct ? `±${res.rules.price_move_pct}% price moves` : `${res.rules.volume_multiple}× normal volume`}. Opening your rules so you can see the new noise level.</div>}
      {res?.intent === 'error' && <div className="card card-pad fadein" style={{ marginTop: 14 }}>{res.message}</div>}
      {res?.intent === 'ask' && res.answer && (
        <div className="card fadein" style={{ marginTop: 14 }}>
          <div className="card-pad small muted" style={{ paddingBottom: 0 }}>{res.name} · from its own transcripts and annual report</div>
          <div className="qa-a">{cite(res.answer.answer, res.answer.links)}</div>
          <div className="story-foot"><span className="tiny muted">confidence {res.answer.confidence}</span><button className="link" onClick={() => act({ ...res, intent: 'research' })}>Open dossier {Icon.arrow}</button></div>
        </div>
      )}
      {res && <div className="tiny muted" style={{ marginTop: 12 }}>Understood by {res.routed_by === 'rules' ? 'pattern rules (no model call)' : 'flash-lite'}.</div>}
    </Sheet>
  )
}
