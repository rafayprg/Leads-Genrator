import { api } from '../api.js'
import { SALES_STATES, badge, banner, fill, h, icon, pageHead, reveal, salesBadge, toast, when } from '../ui.js'
import { scoreRing } from './overview.js'

const FAST_MS = 5000 // while audits are running
const SLOW_MS = 20000
const BANDS = ['High priority', 'Medium-high', 'Qualify further', 'Lower priority']
const REPORT_NAME = { owner_summary: 'Owner', internal_sales: 'Sales brief' }
const RANK = { viewer: 0, sales: 1, admin: 2 }

function runCard(r, selected) {
  const pct = Math.round((100 * r.done) / Math.max(r.total, 1))
  const state = r.active ? h('span', { class: 'live', text: `${r.active} running` })
    : r.finished_at ? badge(`done ${when(r.finished_at)}`, 'ok') : badge('stopped', 'warn')
  return h('a', { class: `card run-card ${selected ? 'on' : ''}`, href: `#/results/${r.key}` },
    h('div', { class: 'row-between' }, h('b', { text: r.label }), state),
    h('div', { class: 'bar' }, h('i', { style: `width:${pct}%` })),
    h('div', { class: 'small mute', text: `${r.done} of ${r.total} done · ${when(r.started_at)}` +
      (r.with_failed_parts ? ` · ${r.with_failed_parts} with a failed part` : '') }))
}

function issues(r) {
  const c = r.issue_counts || {}
  const parts = [['critical', 'bad'], ['high', 'bad'], ['medium', 'warn'], ['low', '']]
    .filter(([k]) => c[k]).map(([k, kind]) => badge(`${c[k]} ${k}`, kind))
  return parts.length ? parts : h('span', { class: 'mute', text: 'none' })
}

/** Quick call status for a row; a follow-up asks for a date. */
function quickStatus(r, onSaved) {
  const sel = h('select', { class: 'quick-status', 'aria-label': `Call status for ${r.name}` },
    h('option', { value: '', text: 'Set status…' }), SALES_STATES.map(([k, label]) => h('option', { value: k, text: label })))
  sel.onchange = async () => {
    if (!sel.value) return
    let follow = null
    if (sel.value === 'follow_up') {
      follow = prompt('Follow-up date (YYYY-MM-DD)', new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10))
      if (!follow) { sel.value = ''; return }
    }
    try {
      await api.post(`/businesses/${r.business_pk}/sales`, { status: sel.value, follow_up_on: follow })
      toast(`${r.name}: ${sel.selectedOptions[0].text}`)
      onSaved()
    } catch (err) { toast(err.message, 'bad'); sel.value = '' }
  }
  return sel
}

function resultRow(r, i, fresh, canSales, onSaved) {
  return h('tr', { class: fresh ? 'fresh' : '', style: `--r:${i}` },
    h('td', {}, scoreRing(r.score)),
    h('td', {}, h('a', { href: `#/leads/${r.business_pk}`, text: r.name }),
      h('div', { class: 'small mute', text: [r.business_id, r.industry, r.city].filter(Boolean).join(' · ') }),
      h('div', {}, r.band ? badge(r.band, r.score >= 60 ? 'ok' : '') : null, r.stale ? badge('stale', 'warn') : null,
        r.failed_parts.length ? badge(`failed: ${r.failed_parts.join(', ')}`, 'warn') : null)),
    h('td', {}, issues(r)),
    h('td', { class: 'small' }, r.top_issues.length ? h('ul', { class: 'tight' }, r.top_issues.map((x) =>
      h('li', { text: x.confirmed ? x.issue : `${x.issue} (to confirm)` }))) : h('span', { class: 'mute', text: '—' })),
    h('td', { class: 'small', style: 'max-width:300px' }, r.opener_roman_urdu
      ? h('details', {}, h('summary', { text: r.opener_roman_urdu }), h('p', { class: 'mute', text: r.opener_en || '' }))
      : h('span', { class: 'mute', text: 'no AI note' })),
    h('td', {}, h('div', {}, salesBadge(r.sales)), canSales ? h('div', { class: 'gap', style: 'margin-top:6px' }, quickStatus(r, onSaved)) : null),
    h('td', { class: 'small' }, r.reports.length ? r.reports.map((rep) => h('div', {},
      h('a', { href: `#/reports/${rep.id}`, text:
        `${REPORT_NAME[rep.type] || rep.type}${rep.language === 'en' ? '' : ' · Roman Urdu'}` }),
      rep.pdf && canSales ? [' · ', h('a', { href: `/api/reports/${rep.id}/pdf`, text: 'PDF' })] : null))
      : h('span', { class: 'mute', text: 'no report' })))
}

/** Audit Results: every finished full audit shows up here as it completes. */
export async function results(root, user, runKey) {
  const canSales = RANK[user.role] >= RANK.sales
  const band = h('select', {}, h('option', { value: '', text: 'All bands' }), BANDS.map((b) => h('option', { value: b, text: b })))
  const sales = h('select', {}, h('option', { value: '', text: 'Any call status' }), h('option', { value: 'not_called', text: 'Not called yet' }),
    SALES_STATES.map(([k, label]) => h('option', { value: k, text: label })))
  const sort = h('select', {}, h('option', { value: 'finished', text: 'Newest finished' }), h('option', { value: 'score', text: 'Highest score' }))
  const q = h('input', { type: 'search', placeholder: 'Name, city or industry' })
  const runsBox = h('div')
  const head = h('div')
  const body = h('div')
  const staleBtn = h('button', { class: 'ghost', disabled: true }, icon('refresh', 15), 'Re-audit stale')
  const seen = new Set()
  let first = true
  let timer = null
  let typing = null

  staleBtn.onclick = async () => {
    staleBtn.disabled = true
    try {
      const r = await api.post('/audits/reaudit-stale')
      toast(r.queued ? `Re-audit started for ${r.queued} lead(s)` : 'Nothing stale to re-audit')
      if (r.run) location.hash = `#/results/${r.run}`
    } catch (err) { toast(err.message, 'bad') }
  }

  async function load() {
    clearTimeout(timer)
    const params = new URLSearchParams({ sort: sort.value, limit: '200' })
    if (runKey) params.set('run', runKey)
    if (band.value) params.set('band', band.value)
    if (sales.value) params.set('sales', sales.value)
    if (q.value.trim()) params.set('q', q.value.trim())
    let data = null
    try {
      data = await api.get(`/results?${params}`)
    } catch (err) {
      fill(body, banner('bad', err.message))
    }
    if (data) {
      const staleCount = data.results.filter((r) => r.stale).length
      staleBtn.disabled = !canSales || !staleCount
      staleBtn.title = `Audits older than ${data.stale_days} days`
      fill(runsBox, data.runs.length ? h('div', { class: 'grid wide' },
        h('a', { class: `card run-card ${data.run ? '' : 'on'}`, href: '#/results' }, h('b', { text: 'All audits' }),
          h('div', { class: 'small mute gap', text: 'Latest audit of every business' })),
        data.runs.map((r) => runCard(r, r.key === data.run))) : null)
      fill(head, h('div', { class: 'row-between' },
        h('span', { class: 'small mute', text: `${data.total} result(s)${data.total > data.results.length ? `, showing ${data.results.length}` : ''}` }),
        data.active ? h('span', { class: 'live', text: `${data.active} audit(s) running — results appear by themselves` }) : null))
      fill(body, data.results.length ? h('div', { class: 'card wrap' }, h('table', { class: first ? 'rows-in hover' : 'hover' },
        h('tr', {}, ...['Score', 'Business', 'Issues', 'Top issues', 'Call opener (Roman Urdu)', 'Call', 'Reports'].map((t) => h('th', { text: t }))),
        data.results.map((r, i) => resultRow(r, i, !first && !seen.has(r.job_id), canSales, load))))
        : h('div', { class: 'card empty' }, icon('results'), h('div', { text: data.active
          ? 'Audits are running — the first results appear here as soon as one finishes.'
          : 'Nothing matches. Start audits from All Leads (“Not audited yet” tab).' })))
      data.results.forEach((r) => seen.add(r.job_id))
      first = false
    }
    timer = setTimeout(load, data && data.active ? FAST_MS : SLOW_MS)
  }

  const reload = () => { first = true; seen.clear(); load() }
  band.onchange = reload
  sales.onchange = reload
  sort.onchange = reload
  q.oninput = () => { clearTimeout(typing); typing = setTimeout(reload, 350) }

  const page = h('div', {},
    pageHead('Audit Results', 'Every finished full audit, as it completes. One bulk click = one run.', staleBtn,
      canSales ? h('a', { class: 'btn', href: '/api/reports/export?format=xlsx' }, icon('download', 15), 'Sales sheet') : null),
    runsBox,
    h('div', { class: 'card' }, h('div', { class: 'row' }, h('div', {}, h('label', {}, 'Band', band)), h('div', {}, h('label', {}, 'Call status', sales)),
      h('div', {}, h('label', {}, 'Sort', sort)), h('div', { class: 'grow' }, h('label', {}, 'Search', q)))),
    head, body)
  reveal(page)
  fill(root, page)
  await load()
  return () => { clearTimeout(timer); clearTimeout(typing) }
}
