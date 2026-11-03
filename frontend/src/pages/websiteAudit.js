import { api } from '../api.js'
import { badge, banner, fill, h, safeLink, statusBadge } from '../ui.js'

const POLL_MS = 3000
const SEV = ['critical', 'high', 'medium', 'low']
const SEV_KIND = { critical: 'bad', high: 'bad', medium: 'warn', low: '' }
const ms = (v) => (v ? `${(v / 1000).toFixed(1)}s` : '—')
const mb = (v) => (v ? `${(v / 1_000_000).toFixed(1)} MB` : '—')

function metricsTable(m) {
  const d = m.desktop || {}
  const mob = m.mobile || {}
  const rows = [
    ['Homepage HTML arrived in', ms(m.home_html_ms)],
    ['Main content visible (desktop)', ms(d.lcp_ms)],
    ['Fully loaded (desktop)', ms(d.load_ms)],
    ['Page weight / requests', d.bytes ? `${mb(d.bytes)} · ${d.requests}` : '—'],
    ['Layout shift (CLS)', d.cls ?? '—'],
    ['Phone: sideways overflow', mob.overflow_px !== undefined ? (mob.overflow_px > 10 ? `${mob.overflow_px}px` : 'none') : '—'],
    ['Phone: call/book buttons on first screen', mob.cta_above_fold ?? '—'],
    ['Pages in sitemap', m.sitemap_urls ?? '—'],
  ]
  return h('table', {}, rows.map(([a, b]) => h('tr', {}, h('td', { class: 'mute', text: a }), h('td', { class: 'num', text: b }))))
}

export function finding(f) {
  const ev = { ...f.evidence }
  return h('details', { class: `finding sev-${f.severity}` },
    h('summary', {}, badge(f.severity, SEV_KIND[f.severity]), ' ', h('b', { text: f.title }),
      h('span', { class: 'mute small' }, `  ${f.category}`)),
    h('div', { class: 'finding-body' },
      f.description ? h('p', {}, h('span', { class: 'mute', text: 'Why it matters: ' }), f.description) : null,
      h('p', {}, h('span', { class: 'mute', text: 'Fix: ' }), f.recommendation || ''),
      h('p', { class: 'small' }, badge(`confidence: ${f.confidence}`), ' ',
        badge(f.verification_status === 'verified' ? 'seen directly' : 'inferred — check before telling the owner',
          f.verification_status === 'verified' ? 'ok' : 'warn'),
        f.source_url ? [' ', safeLink(f.source_url, 'page')] : null),
      h('pre', { class: 'log small', text: JSON.stringify(ev, null, 2) })))
}

/** Website audit block for one business. Returns { el, stop }. */
export function websiteAuditSection(b) {
  const el = h('div', { class: 'card' })
  let timer = null

  async function start(btn) {
    btn.disabled = true
    try {
      await api.post(`/businesses/${b.id}/website-audit`)
    } catch (err) {
      el.prepend(banner('bad', err.message))
    }
    load()
  }

  async function load() {
    clearTimeout(timer)
    const a = await api.get(`/businesses/${b.id}/website-audit`)
    const running = a.task_status === 'pending' || a.task_status === 'running'
    const runBtn = h('button', { text: a.summary ? 'Run again' : 'Run website audit', disabled: running || !b.website_url,
      onclick: (e) => start(e.target) })
    const s = a.summary
    const counts = s ? SEV.map((k) => badge(`${s.by_severity[k] || 0} ${k}`, (s.by_severity[k] || 0) ? SEV_KIND[k] : '')) : []
    const shots = s?.screenshots && Object.keys(s.screenshots).length
      ? h('div', { class: 'shots' }, ['desktop', 'mobile'].filter((k) => s.screenshots[k]).map((k) =>
        h('figure', {}, h('img', { src: `/api/artifacts/${b.business_id}/${a.job_id}/${s.screenshots[k]}`, alt: `${k} screenshot of the homepage`, loading: 'lazy' }),
          h('figcaption', { class: 'mute small', text: k }))))
      : null
    fill(el,
      h('div', { class: 'row-between' }, h('b', { text: 'Website audit (Agent 1)' }),
        h('span', {}, a.task_status ? statusBadge(a.task_status) : null, ' ', runBtn)),
      !b.website_url ? h('p', { class: 'mute', text: 'No website on record, so there is nothing to audit.' }) : null,
      running ? h('p', { class: 'mute', text: 'Agent 1 is checking the site (pages, links, SEO, phone layout, speed, accessibility)… usually under a minute.' }) : null,
      a.error ? banner('warn', `Last attempt had a problem: ${a.error}`) : null,
      !a.task_status && b.website_url ? h('p', { class: 'mute', text: 'Not audited yet.' }) : null,
      s ? h('div', {},
        h('p', {}, `Checked ${s.pages_inspected} page(s) · ${s.issues_found} issue(s) `, ...counts),
        s.status === 'failed' ? banner('bad', 'The website did not load during the audit.') : null,
        h('div', { class: 'grid wide' }, h('div', {}, metricsTable(s.metrics || {})), shots),
        a.findings.length ? h('div', { class: 'findings' }, a.findings.map(finding)) : h('p', { class: 'ok', text: 'No issues found.' }),
        s.limitations?.length ? h('div', { class: 'small mute' }, h('b', { text: 'Limits of this audit: ' }), s.limitations.join(' · ')) : null,
        h('p', { class: 'small mute', text: `Pages inspected: ${Object.entries(s.pages || {}).map(([k, u]) => `${k} (${u})`).join(', ')}` }))
        : null,
    )
    if (running) timer = setTimeout(load, POLL_MS)
  }

  load().catch((err) => el.replaceChildren(banner('bad', err.message)))
  return { el, stop: () => clearTimeout(timer) }
}
