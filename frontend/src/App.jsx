import { useEffect, useRef, useState } from 'react'
import { DEFAULT_RULES, api, store } from './api'
import Brief from './Brief'
import Command from './Command'
import Holdings, { CompanySheet } from './Holdings'
import Research from './Research'
import Rules from './Rules'
import { Icon } from './ui'

const TABS = [['brief', 'Brief', Icon.brief], ['book', 'Holdings', Icon.book], ['ask', 'Research', Icon.ask], ['rules', 'Rules', Icon.rules]]

export default function App() {
  const [tab, setTab] = useState(() => (location.hash.slice(1).split('/')[0] || 'brief'))
  const [rules, setRulesState] = useState(() => store.get('rules', DEFAULT_RULES))
  const [muted, setMuted] = useState(() => store.get('muted', []))
  const [notify, setNotifyState] = useState(() => store.get('notify', false))
  const [sheet, setSheet] = useState(null)
  const [symbol, setSymbol] = useState(() => (location.hash.startsWith('#ask/') ? location.hash.slice(5) : null))
  const [demo, setDemo] = useState(null)
  const [matters, setMatters] = useState(0)
  const [scrolled, setScrolled] = useState(false)
  const [health, setHealth] = useState(null)
  const [lastVisit] = useState(() => store.get('lastVisit', null))
  const [cmd, setCmd] = useState(null)
  const [briefWin, setBriefWin] = useState(null)
  const seen = useRef(new Set(store.get('seen', [])))

  useEffect(() => {
    api.demo().then(setDemo).catch(() => {})
    api.health().then(setHealth).catch(() => {})
    const onScroll = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', onScroll, { passive: true })
    const bye = () => store.set('lastVisit', new Date().toISOString())
    window.addEventListener('pagehide', bye)
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {})
    return () => { window.removeEventListener('scroll', onScroll); window.removeEventListener('pagehide', bye) }
  }, [])

  useEffect(() => { location.hash = tab === 'ask' && symbol ? `ask/${symbol}` : tab; window.scrollTo(0, 0) }, [tab, symbol])

  // Push while open/installed: poll the brief, notify on newly material stories.
  useEffect(() => {
    if (!notify) return
    const check = () => api.digest({ hours: 24, ...rules }).then((d) => {
      d.stories.filter((s) => s.tier === 'matters' && !seen.current.has(s.id)).forEach((s) => {
        seen.current.add(s.id)
        navigator.serviceWorker?.ready.then((reg) => reg.showNotification(`${s.symbol} · ${s.label}`, { body: s.enrich?.takeaway || s.enrich?.headline || s.oneliner || s.title, icon: '/icon.svg', tag: s.id }))
          .catch(() => new Notification(`${s.symbol} · ${s.label}`, { body: s.oneliner || s.title }))
      })
      store.set('seen', [...seen.current].slice(-300))
    }).catch(() => {})
    const id = setInterval(check, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [notify, rules])

  const setRules = (r) => { setRulesState(r); store.set('rules', r) }
  const setNotify = (v) => { setNotifyState(v); store.set('notify', v) }
  const mute = (c) => { const m = [...new Set([...muted, c])]; setMuted(m); store.set('muted', m) }
  const unmute = (c) => { const m = muted.filter((x) => x !== c); setMuted(m); store.set('muted', m) }
  const research = (s, mode) => {
    if (mode === 'company') return setSheet(s)
    setSheet(null); setSymbol(s); setTab('ask')
  }

  const act = (r) => {
    setCmd(null)
    if (r.intent === 'brief') { setBriefWin(r.window_hours || null); setSymbol(null); setTab('brief') }
    else if (r.intent === 'company') { setSheet(r.symbol) }
    else if (r.intent === 'research' || r.intent === 'ask') { setSheet(null); setSymbol(r.symbol); setTab('ask') }
    else if (r.intent === 'rules') { setRules({ ...rules, ...r.rules }); setTab('rules') }
  }

  const busy = health?.feed?.running
  return (
    <div className="app">
      <header className={`top ${scrolled ? 'scrolled' : ''}`}>
        <button className="brand" onClick={() => { setTab('brief'); setSymbol(null) }}>FINN<i /></button>
        {tab === 'ask' && symbol
          ? <button className="chip small" onClick={() => setSymbol(null)}>← All research</button>
          : <span className="live"><span className={`dot ${busy ? 'busy' : ''}`} />{health?.llm === false ? 'Numbers-only mode' : busy ? 'Checking feeds' : 'Watching 18 holdings'}</span>}
      </header>
      <main>
        {tab === 'brief' && <Brief key={`b${briefWin}`} initialWin={briefWin} rules={rules} muted={muted} onMute={mute} onUnmute={unmute} lastVisit={lastVisit} onResearch={research} onAlertCount={setMatters} />}
        {tab === 'book' && <Holdings onOpen={setSheet} />}
        {tab === 'ask' && <Research symbol={symbol} setSymbol={setSymbol} demo={demo} />}
        {tab === 'rules' && <Rules rules={rules} setRules={setRules} notify={notify} setNotify={setNotify} />}
      </main>
      {!cmd && (
        <button className="fab" onClick={() => setCmd('text')} aria-label="Ask FINN">
          {Icon.spark}<span>Ask FINN</span>
        </button>
      )}
      {cmd && <Command onClose={() => setCmd(null)} act={act} autoVoice={cmd === 'voice'} />}
      {sheet && <CompanySheet symbol={sheet} onClose={() => setSheet(null)} onResearch={research} />}
      <nav className="tabs">
        {TABS.map(([k, l, ic]) => (
          <button key={k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => { setTab(k); if (k === 'ask' && tab === 'ask') setSymbol(null) }}>
            {ic}{l}
            {k === 'brief' && matters > 0 && tab !== 'brief' && <span className="badge">{matters}</span>}
          </button>
        ))}
      </nav>
    </div>
  )
}
