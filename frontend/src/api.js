const j = async (r) => {
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return r.json()
}
const qs = (o) =>
  Object.entries(o)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(Array.isArray(v) ? v.join(',') : v)}`)
    .join('&')

export const api = {
  digest: (p) => fetch(`/api/digest?${qs(p)}`).then(j),
  portfolio: () => fetch('/api/portfolio').then(j),
  company: (s) => fetch(`/api/company/${s}`).then(j),
  preview: (p) => fetch(`/api/rules/preview?${qs(p)}`).then(j),
  search: (q) => fetch(`/api/search?q=${encodeURIComponent(q)}`).then(j),
  research: (s, force) => fetch(`/api/research/${s}${force ? '?force=true' : ''}`, { method: 'POST' }).then(j),
  researchStatus: (s) => fetch(`/api/research/${s}`).then(j),
  ask: (symbol, question) =>
    fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, question }) }).then(j),
  health: () => fetch('/api/health').then(j),
  demo: () => fetch('/api/demo').then(j),
}

// Small persisted prefs (per-viewer conveniences only).
export const store = {
  get(k, d) {
    try {
      const v = localStorage.getItem('finn:' + k)
      return v == null ? d : JSON.parse(v)
    } catch {
      return d
    }
  },
  set(k, v) {
    try {
      localStorage.setItem('finn:' + k, JSON.stringify(v))
    } catch {}
  },
}

export const DEFAULT_RULES = {
  price_move_pct: 5,
  volume_multiple: 2,
  categories: ['results', 'M&A', 'management_change', 'fund_raise', 'litigation', 'pledging', 'credit_rating', 'insider_trading'],
}

export const CATS = [
  ['results', 'Results'], ['M&A', 'M&A'], ['management_change', 'People'], ['fund_raise', 'Fund raise'],
  ['litigation', 'Legal / regulatory'], ['insider_trading', 'Insider deals'], ['pledging', 'Pledges'],
  ['credit_rating', 'Credit rating'], ['capex', 'Capex'], ['dividend', 'Dividend'], ['bonus_split', 'Bonus / split'],
  ['press_release', 'Orders & updates'], ['earnings_call', 'Earnings calls'],
]
