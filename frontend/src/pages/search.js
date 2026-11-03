import { api, meta } from '../api.js'
import { badge, banner, chip, fill, h, icon, money, pageHead, reveal, statusBadge, toast, when } from '../ui.js'

const POLL_MS = 2000
const AUDIT_PARTS = [
  ['website', 'Website (Agent 1)'], ['social_finder', 'Social finder (Agent 3)'], ['social', 'Social media (Agent 2)'],
  ['automation', 'Automation (Agent 4)'], ['organizer', 'Organizer (Agent 5)'], ['reporting', 'Report (Agent 6)'],
]
const PLACES = [20, 40, 80, 150]

const step = (n, title, sub, ...body) => h('section', { class: 'card step' },
  h('div', { class: 'step-head' }, h('span', { class: 'step-n', text: n }), h('div', {}, h('h2', { text: title }), sub ? h('p', { class: 'small mute', text: sub }) : null)),
  ...body)

/**
 * Dropdown with ticks for the cities of one country: search, all / none, and a short summary on the button.
 * @param {string} title @param {string[]} items @param {Set<string>} off  items NOT wanted @param {() => void} onChange
 */
function multiPick(title, items, off, onChange) {
  const btn = h('button', { type: 'button', class: 'pick-btn', 'aria-haspopup': 'listbox', 'aria-expanded': 'false' })
  const list = h('div', { class: 'pick-list', role: 'listbox', 'aria-multiselectable': 'true' })
  const find = h('input', { type: 'search', placeholder: `Search ${items.length} cities`, 'aria-label': `Search cities in ${title}` })
  const panel = h('div', { class: 'pick-panel', hidden: true },
    h('div', { class: 'pick-tools' }, find,
      h('button', { type: 'button', class: 'ghost small', text: 'All', onclick: () => { items.forEach((c) => off.delete(c)); sync() } }),
      h('button', { type: 'button', class: 'ghost small', text: 'None', onclick: () => { items.forEach((c) => off.add(c)); sync() } })),
    list)
  const [code, name] = title.split('|')
  const wrap = h('div', { class: 'pick' }, h('div', { class: 'pick-label' }, h('span', { class: 'cc', text: code }), name), btn, panel)

  function summary() {
    const on = items.filter((c) => !off.has(c))
    if (!on.length) return h('span', { class: 'mute', text: 'No city picked' })
    if (on.length === items.length) return [h('b', { text: `All ${items.length} cities` })]
    return [h('b', { text: on.slice(0, 2).join(', ') }), on.length > 2 ? h('span', { class: 'mute', text: ` +${on.length - 2} more` }) : null]
  }
  function drawList() {
    const q = find.value.trim().toLowerCase()
    fill(list, items.filter((c) => c.toLowerCase().includes(q)).map((c) => {
      const box = h('input', { type: 'checkbox', tabindex: -1 })
      box.checked = !off.has(c)
      return h('label', { class: 'pick-item', role: 'option', 'aria-selected': String(!off.has(c)) }, box, c)
    }))
    list.querySelectorAll('.pick-item').forEach((row) => {
      const name = row.textContent
      row.querySelector('input').onchange = (e) => { if (e.target.checked) off.delete(name); else off.add(name); sync() }
    })
  }
  function sync() {
    fill(btn, h('span', { class: 'pick-sum' }, summary()), icon('arrow', 14))
    drawList()
    onChange()
  }
  const close = () => { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); wrap.classList.remove('open') }
  btn.onclick = () => {
    const opening = panel.hidden
    document.querySelectorAll('.pick.open').forEach((p) => p !== wrap && p.dispatchEvent(new Event('pick-close')))
    panel.hidden = !opening
    wrap.classList.toggle('open', opening)
    btn.setAttribute('aria-expanded', String(opening))
    if (opening) setTimeout(() => find.focus(), 30)
  }
  wrap.addEventListener('pick-close', close)
  wrap.addEventListener('keydown', (e) => { if (e.key === 'Escape') { close(); btn.focus() } })
  find.oninput = drawList
  fill(btn, h('span', { class: 'pick-sum' }, summary()), icon('arrow', 14))
  drawList()
  return wrap
}

/** @param {HTMLElement} root */
export async function search(root) {
  const [m, acc] = await Promise.all([meta(), api.get('/apify/accounts')])
  const regions = [...new Set(Object.values(m.countries).map((c) => c.region))]
  const state = {
    countries: new Set(['AE']),
    off: Object.fromEntries(Object.keys(m.countries).map((cc) => [cc, new Set()])), // cities NOT wanted, per country
    industries: new Set(['beauty']),
    budget: 2,
    perSearch: 40,
    minReviews: 50,
    maxReviews: 1000,
    audit: false,
    auditParts: new Set(AUDIT_PARTS.map(([k]) => k)),
  }
  let timer = null
  let estTimer = null

  const countryBox = h('div')
  const cityBox = h('div', { class: 'pick-grid' })
  const summary = h('div')
  const startBtn = h('button', { type: 'submit', class: 'start' }, icon('search', 16), 'Start search')
  const runBox = h('div')
  const history = h('div')

  const targets = () => [...state.countries].flatMap((cc) =>
    m.countries[cc].cities.filter((c) => !state.off[cc].has(c)).map((city) => ({ country: cc, city })))
  const body = () => ({
    targets: targets(), industries: [...state.industries], budget_usd: state.budget, per_search: state.perSearch,
    min_reviews: state.minReviews, max_reviews: state.maxReviews,
    audit: state.audit ? Object.fromEntries(AUDIT_PARTS.map(([k]) => [k, state.auditParts.has(k)])) : null,
  })

  function drawCountries() {
    fill(countryBox, regions.map((region) => {
      const ccs = Object.keys(m.countries).filter((cc) => m.countries[cc].region === region)
      const allOn = ccs.every((cc) => state.countries.has(cc))
      return h('div', { class: 'region' },
        h('div', { class: 'region-head' }, h('span', { class: 'small mute', text: region }),
          h('button', { type: 'button', class: 'linkish', text: allOn ? `Clear ${region}` : `All ${region}`, onclick: () => {
            ccs.forEach((cc) => (allOn ? state.countries.delete(cc) : state.countries.add(cc)))
            changed()
          } })),
        h('div', { class: 'chips' }, ccs.map((cc) => chip(m.countries[cc].name, cc, state.countries.has(cc), (e) => {
          if (e.target.checked) state.countries.add(cc); else state.countries.delete(cc)
          changed()
        }))))
    }))
  }

  function drawCities() {
    const picked = [...state.countries]
    fill(cityBox, picked.length
      ? picked.map((cc) => multiPick(`${cc}|${m.countries[cc].name}`, m.countries[cc].cities, state.off[cc], estimate))
      : h('p', { class: 'mute small', text: 'Pick a country first.' }))
  }

  function changed() { drawCountries(); drawCities(); estimate() }

  function estimate() {
    clearTimeout(estTimer)
    estTimer = setTimeout(async () => {
      const b = body()
      const blocked = !acc.accounts.length || acc.credit_left_usd < m.apify.min_run_usd || !b.targets.length ||
        !b.industries.length || b.budget_usd < m.apify.min_run_usd
      startBtn.disabled = blocked
      const line = (k, v) => h('div', { class: 'sum-row' }, h('span', { class: 'mute', text: k }), h('b', {}, v))
      if (!b.targets.length || !b.industries.length) {
        fill(summary, h('p', { class: 'mute small', text: !b.targets.length ? 'Pick at least one city.' : 'Pick at least one industry.' }))
        return
      }
      if (b.min_reviews > b.max_reviews) {
        fill(summary, banner('warn', 'Minimum reviews is more than maximum. Fix the review range.'))
        startBtn.disabled = true
        return
      }
      if (b.targets.length > 80) {
        fill(summary, banner('warn', `${b.targets.length} cities picked — one run can take up to 80. Untick some.`))
        startBtn.disabled = true
        return
      }
      try {
        const e = await api.post('/searches/estimate', b)
        const over = e.estimate_usd > e.budget_usd
        fill(summary,
          line('Cities', String(e.cities)), line('Searches', String(e.searches)), line('Up to', `${e.max_places.toLocaleString()} places`),
          line('Google reviews', `${b.min_reviews.toLocaleString()} – ${b.max_reviews.toLocaleString()}`),
          h('div', { class: 'sum-total' }, h('span', { class: 'mute small', text: 'Full cost would be about' }), h('div', { class: 'big', text: money(e.estimate_usd) })),
          h('div', { class: 'bar' }, h('i', { style: `width:${Math.min(100, (100 * e.budget_usd) / Math.max(e.estimate_usd, 0.01))}%` })),
          h('p', { class: 'small mute', text: over
            ? `Stops at your cap of ${money(e.budget_usd)} — about ${Math.round((100 * e.budget_usd) / e.estimate_usd)}% of it gets done. Raise the cap to cover it all.`
            : `Fits inside your cap of ${money(e.budget_usd)}.` }),
          line('Credit left', money(e.credit_left_usd)))
      } catch (err) {
        fill(summary, banner('bad', err.message))
      }
    }, 250)
  }

  const industryGrid = h('div', { class: 'ind-grid' }, Object.entries(m.industries).map(([k, v]) => {
    const box = h('input', { type: 'checkbox', value: k, onchange: (e) => {
      if (e.target.checked) state.industries.add(k); else state.industries.delete(k)
      estimate()
    } })
    box.checked = state.industries.has(k)
    return h('label', { class: 'ind' }, box, h('span', {}, h('b', { text: v.label }),
      h('span', { class: 'small mute', text: `${v.searches} search${v.searches === 1 ? '' : 'es'} per city${v.tier === 1 ? ' · best fit' : ''}` })))
  }))

  const budget = h('input', { type: 'range', min: m.apify.min_run_usd, max: 20, step: 0.5, value: state.budget, 'aria-label': 'Apify budget for this run' })
  const budgetNum = h('input', { type: 'number', min: m.apify.min_run_usd, max: 200, step: 0.5, value: state.budget, class: 'budget-num', 'aria-label': 'Apify budget in dollars' })
  const setBudget = (v) => { state.budget = Number(v) || 0; budget.value = Math.min(20, state.budget); budgetNum.value = state.budget; estimate() }
  budget.oninput = (e) => setBudget(e.target.value)
  budgetNum.oninput = (e) => setBudget(e.target.value)

  const places = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'Places per search' }, PLACES.map((n) => h('button', {
    type: 'button', role: 'radio', class: n === state.perSearch ? 'on' : '', 'aria-checked': String(n === state.perSearch), text: String(n), onclick: (e) => {
      state.perSearch = n
      places.querySelectorAll('button').forEach((x) => { x.classList.toggle('on', x === e.currentTarget); x.setAttribute('aria-checked', String(x === e.currentTarget)) })
      estimate()
    } })))

  const reviewInput = (key, label) => h('input', {
    type: 'number', min: 0, max: 100000, step: 10, value: state[key], class: 'budget-num', 'aria-label': label,
    oninput: (e) => { state[key] = Math.max(0, Math.round(Number(e.target.value) || 0)); estimate() },
  })
  const reviews = h('div', { class: 'row' },
    h('div', {}, h('label', { text: 'Google reviews — minimum' }), reviewInput('minReviews', 'Minimum Google reviews')),
    h('div', {}, h('label', { text: 'maximum' }), reviewInput('maxReviews', 'Maximum Google reviews')))

  const auditBox = h('div', { class: 'chips gap', hidden: true }, AUDIT_PARTS.map(([k, label]) =>
    chip(label, k, true, (e) => { if (e.target.checked) state.auditParts.add(k); else state.auditParts.delete(k) })))
  const auditToggle = h('label', { class: 'switch' }, h('input', { type: 'checkbox', role: 'switch', onchange: (e) => {
    state.audit = e.target.checked
    auditBox.hidden = !state.audit
  } }), h('span', { class: 'track' }), h('span', {}, h('b', { text: 'Audit every new lead' }), h('span', { class: 'small mute', text: ' — free, reads their websites' })))

  async function showRun(id) {
    clearTimeout(timer)
    const r = await api.get(`/searches/${id}`)
    const log = h('pre', { class: 'log', text: r.log.slice(-60).join('\n') })
    fill(runBox, h('div', { class: 'card' },
      h('div', { class: 'section-title' }, h('h2', { text: `Search #${r.id}` }), statusBadge(r.status)),
      r.problem ? banner('bad', r.problem) : null,
      h('div', { class: 'grid tight' },
        ...[['Places found', r.records_found], ['New leads', r.new_businesses], ['Already known', r.updated_businesses],
          ['Rejected', r.rejected.length], ['Apify spent', money(r.spent_usd)]].map(([l, n]) =>
          h('div', {}, h('div', { class: 'small mute', text: l }), h('div', { class: 'big', text: n })))),
      r.actor_runs.length ? h('table', {}, r.actor_runs.map((a) => h('tr', {},
        h('td', { text: [a.city, a.industry].filter(Boolean).join(' · ') || 'run' }), h('td', { class: 'mute', text: a.account }),
        h('td', {}, badge(a.status, a.status === 'SUCCEEDED' ? 'ok' : '')), h('td', { class: 'num', text: `${a.items} places` }),
        h('td', { class: 'num', text: money(a.cost_usd) })))) : null,
      log,
      r.status === 'completed' || r.status === 'partial' ? h('a', { href: '#/leads', class: 'btn ghost gap' }, 'See the new leads', icon('arrow', 14)) : null))
    log.scrollTop = log.scrollHeight
    if (r.status === 'queued' || r.status === 'running') timer = setTimeout(() => showRun(id), POLL_MS)
    else loadHistory()
  }

  async function loadHistory() {
    const runs = await api.get('/searches?limit=10')
    fill(history, h('div', { class: 'card wrap' }, h('h2', { text: 'Earlier searches' }),
      runs.length ? h('table', { class: 'hover' }, h('tr', {}, ...['When', 'Where', 'What', 'Status', 'New', 'Spent'].map((t, i) => h('th', { class: i > 3 ? 'num' : '', text: t }))),
        runs.map((r) => h('tr', { class: 'click', onclick: () => showRun(r.id) },
          h('td', { class: 'mute small', text: when(r.created_at) }),
          h('td', { text: r.params.targets.map((t) => t[1]).slice(0, 4).join(', ') + (r.params.targets.length > 4 ? ` +${r.params.targets.length - 4}` : '') }),
          h('td', { class: 'small', text: r.params.industries.map((k) => m.industries[k]?.label || k).join(', ') }),
          h('td', {}, statusBadge(r.status)),
          h('td', { class: 'num', text: r.new_businesses }),
          h('td', { class: 'num', text: money(r.spent_usd) }))))
        : h('p', { class: 'mute small', text: 'None yet.' })))
    const active = runs.find((r) => r.status === 'queued' || r.status === 'running')
    if (active && !timer) showRun(active.id)
  }

  const form = h('form', { class: 'search-layout', onsubmit: async (e) => {
    e.preventDefault()
    startBtn.disabled = true
    try {
      const run = await api.post('/searches', body())
      toast('Search started')
      showRun(run.id)
      runBox.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      estimate()
    }
  } },
    h('div', { class: 'steps' },
      step(1, 'Countries', 'Tick one or more. Urdu / Hindi is spoken widely in all of them.', countryBox),
      step(2, 'Cities', 'Every city of a ticked country is on. Open a list to leave some out.', cityBox),
      step(3, 'Industries', 'Each one runs a few Google Maps searches per city.', industryGrid),
      step(4, 'Budget & size', null,
        h('div', { class: 'row' },
          h('div', { class: 'grow' }, h('label', { text: 'Stop spending at (USD, Apify)' }), h('div', { class: 'budget' }, budget, budgetNum)),
          h('div', {}, h('label', { text: 'Places per search' }), places)),
        h('div', { class: 'gap' }, reviews,
          h('p', { class: 'small mute', text: 'Only places with this many Google Maps reviews are kept. Apify still charges for the places it reads.' })),
        h('div', { class: 'gap' }, auditToggle), auditBox)),
    h('aside', { class: 'card summary' }, h('h2', { text: 'This run' }), summary, startBtn,
      h('p', { class: 'small mute', text: `$${m.apify.price_per_place} per place + $${m.apify.price_per_review} for the newest review date. Nothing is spent before you press Start.` })))

  const page = h('div', {},
    pageHead('Lead Search', 'Find businesses on Google Maps. You see the cost before anything is spent.'),
    acc.accounts.length ? null : banner('bad', 'No Apify account saved, so nothing can run. Add one in ', h('a', { href: '#/settings', text: 'Settings' }), '.'),
    acc.accounts.length && acc.credit_left_usd < m.apify.min_run_usd ? banner('bad', `All Apify accounts are out of credit (${money(acc.credit_left_usd)} left).`) : null,
    form, runBox, history)
  const outside = (e) => { if (!e.target.closest('.pick')) document.querySelectorAll('.pick.open').forEach((p) => p.dispatchEvent(new Event('pick-close'))) }
  document.addEventListener('click', outside)
  drawCountries()
  drawCities()
  reveal(page)
  fill(root, page)
  estimate()
  loadHistory()
  return () => { clearTimeout(timer); clearTimeout(estTimer); document.removeEventListener('click', outside) }
}
