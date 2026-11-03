import { api, meta } from '../api.js'
import { can, ownerName, teamList } from '../access.js'
import { badge, chip, fill, h, icon, pageHead, reveal, safeLink, toast, when } from '../ui.js'
import { scoreRing } from './overview.js'

const PAGE_SIZE = 50
// kept while you move between pages
const filters = { audit: 'new', country: new Set(), city: '', industry: '', q: '', offset: 0, sort: 'newest', owner: '' }
const TABS = [['new', 'Not audited yet'], ['audited', 'Audited']]

function select(options, value, onchange) {
  return h('select', { onchange }, options.map(([v, t]) => { const o = h('option', { value: v, text: t }); o.selected = value === v; return o }))
}

function leadRow(b, i, team, picked, onPick) {
  const open = () => { location.hash = `#/leads/${b.id}` }
  const owner = ownerName(team, b.owner_id)
  const box = picked ? h('input', { type: 'checkbox', 'aria-label': `Pick ${b.name}`, onclick: (e) => e.stopPropagation(), onchange: (e) => onPick(b.id, e.target.checked) }) : null
  if (box) box.checked = picked.has(b.id)
  return h('tr', { class: 'click', style: `--r:${i}`, tabindex: 0, onclick: open, onkeydown: (e) => { if (e.key === 'Enter') open() } },
    picked ? h('td', { onclick: (e) => e.stopPropagation() }, box) : null,
    h('td', {}, b.details?.opportunity ? scoreRing(b.details.opportunity.score) : h('span', { class: 'mute', text: '—' })),
    h('td', {}, h('b', { text: b.name }), h('div', { class: 'mute small', text: [b.business_id, b.category || b.industry].filter(Boolean).join(' · ') })),
    h('td', { class: 'mono', text: b.phone || '—' }),
    h('td', {}, b.city || '', h('div', { class: 'mute small', text: b.area || '' })),
    h('td', {}, owner ? badge(owner, 'run') : h('span', { class: 'mute small', text: 'nobody' })),
    h('td', { onclick: (e) => e.stopPropagation() }, b.website_url ? safeLink(b.website_url, 'open') : h('span', { class: 'mute', text: 'none' })),
    h('td', { class: 'mute small', text: when(b.created_at) }))
}

/** @param {HTMLElement} root */
export async function leads(root, user) {
  const [m, team, canAssign, canAudit, canExport] = await Promise.all([meta(), teamList(), can(user, 'assign_leads'),
    can(user, 'start_audits'), can(user, 'export')])
  const fromLink = new URLSearchParams(location.hash.split('?')[1] || '').get('owner')
  if (fromLink !== null) { filters.owner = fromLink; filters.audit = 'audited'; filters.offset = 0 }
  const active = team.filter((t) => t.is_active)
  const list = h('div', { class: 'card wrap' })
  const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Audit state' })
  const picked = canAssign ? new Set() : null
  let typing = null
  const ownerBar = h('div', { class: 'gap' })
  const splitBox = canAssign ? h('div') : null
  const shares = {} // member id -> how many unassigned leads they get

  /** "Fareed 50, Waleed 30": the unassigned leads of these filters, best score first, split by count. */
  function drawSplit(free) {
    const callers = active.filter((t) => t.role === 'caller' || t.role === 'sales')
    const inputs = callers.map((t) => {
      const box = h('input', { type: 'number', min: 0, max: free, value: shares[t.id] || '', placeholder: '0', style: 'width:80px', 'aria-label': `Leads for ${t.name}`,
        oninput: (e) => { shares[t.id] = Math.max(0, Math.floor(Number(e.target.value) || 0)); sum() } })
      return h('label', { class: 'split-member' }, h('span', { text: t.name }), box)
    })
    const total = h('b')
    const go = h('button', {}, icon('arrow', 14), 'Assign')
    const sum = () => {
      const n = Object.values(shares).reduce((a, b) => a + b, 0)
      total.textContent = `${n} of ${free}`
      total.style.color = n > free ? 'var(--bad, #dc2626)' : ''
      go.disabled = !n
    }
    const even = h('button', { class: 'ghost small', text: 'Split evenly', onclick: () => {
      const per = Math.floor(free / Math.max(1, callers.length))
      callers.forEach((t, i) => { shares[t.id] = per + (i < free - per * callers.length ? 1 : 0) })
      drawSplit(free)
    } })
    const clear = h('button', { class: 'ghost small', text: 'Clear', onclick: () => { Object.keys(shares).forEach((k) => delete shares[k]); drawSplit(free) } })
    go.onclick = async () => {
      const list = callers.filter((t) => shares[t.id]).map((t) => ({ user_id: t.id, count: shares[t.id] }))
      if (!confirm(`Give ${list.map((s) => `${ownerName(team, s.user_id)} ${s.count}`).join(', ')} from the ${free} unassigned leads (best score first)?`)) return
      go.disabled = true
      try {
        const r = await api.post('/leads/distribute', { country: [...filters.country], city: filters.city || null, industry: filters.industry || null,
          q: filters.q || null, audit: 'all', shares: list })
        toast(r.per_member.map((x) => `${x.name} ${x.assigned}`).join(' · ') + (r.assigned < list.reduce((a, s) => a + s.count, 0) ? ` (only ${r.available} were free)` : ''))
        Object.keys(shares).forEach((k) => delete shares[k])
        load()
      } catch (err) { toast(err.message, 'bad'); go.disabled = false }
    }
    fill(splitBox, h('section', { class: 'card' },
      h('div', { class: 'section-title' }, h('h2', { text: 'Split unassigned leads' }), badge(`${free} unassigned`, 'warn')),
      h('p', { class: 'small mute', text: 'Uses the country, city, industry and search filters below (audited or not). Type how many each member gets; best score first.' }),
      h('div', { class: 'split-grid' }, inputs),
      h('div', { class: 'row gap', style: 'align-items:center;flex-wrap:wrap;margin-top:10px' }, h('span', { class: 'small' }, 'Total: ', total), even, clear, go)))
    sum()
  }

  async function assignPicked(userId) {
    if (!picked.size) return
    try {
      const r = await api.post('/leads/assign', { business_ids: [...picked], user_id: userId })
      toast(userId ? `${r.assigned} lead(s) given to ${ownerName(team, userId)}` : `${r.assigned} lead(s) unassigned`)
      picked.clear()
      load()
    } catch (err) { toast(err.message, 'bad') }
  }

  async function load() {
    const p = new URLSearchParams()
    filters.country.forEach((c) => p.append('country', c))
    if (filters.city) p.set('city', filters.city)
    if (filters.industry) p.set('industry', filters.industry)
    if (filters.q) p.set('q', filters.q)
    // assigned / unassigned for the same filters (any audit state), and the split panel
    const noOwner = p.toString()
    const [assignedN, freeN] = await Promise.all(['any', 'none'].map((o) => api.get(`/businesses?${noOwner}&owner=${o}&limit=1`).then((r) => r.total)))
    fill(ownerBar, h('div', { class: 'row gap', style: 'align-items:center;flex-wrap:wrap' },
      h('button', { class: `ghost small ${filters.owner === 'any' ? 'on' : ''}`, onclick: () => { filters.owner = filters.owner === 'any' ? '' : 'any'; reload() } }, 'Assigned ', badge(String(assignedN), 'run')),
      h('button', { class: `ghost small ${filters.owner === 'none' ? 'on' : ''}`, onclick: () => { filters.owner = filters.owner === 'none' ? '' : 'none'; reload() } }, 'Unassigned ', badge(String(freeN), 'warn')),
      h('span', { class: 'small mute', text: 'for the filters below (both tabs)' })))
    if (splitBox) drawSplit(freeN)
    if (filters.owner) p.set('owner', filters.owner)
    // both tabs show their count for the same filters; only the list of the open tab is loaded in full
    const counts = await Promise.all(TABS.map(([k]) => api.get(`/businesses?${p}&audit=${k}&limit=1`).then((r) => r.total)))
    fill(tabs, TABS.map(([k, label], i) => h('button', { class: `tab ${filters.audit === k ? 'on' : ''}`, role: 'tab', 'aria-selected': String(filters.audit === k),
      onclick: () => { filters.audit = k; filters.sort = k === 'audited' ? 'score' : 'newest'; reload() } }, label, h('span', { class: 'count-pill', text: counts[i] }))))
    p.set('audit', filters.audit)
    const exportUrl = (fmt) => `/api/businesses/export?format=${fmt}&${p}`
    const bulkQuery = p.toString()
    p.set('sort', filters.sort)
    p.set('limit', PAGE_SIZE)
    p.set('offset', filters.offset)
    const page = await api.get(`/businesses?${p}`)
    const bulk = filters.audit !== 'new'
      ? h('a', { class: 'btn small', href: '#/results' }, 'See results', icon('arrow', 14))
      : canAudit ? h('button', { class: 'small', disabled: !page.total, onclick: async (e) => {
        if (!confirm(`Run a full audit (all agents) for up to 50 of the ${page.total} leads in this list? This reads their websites; no Apify credit is used.`)) return
        e.currentTarget.disabled = true
        try {
          const r = await api.post(`/audits/bulk?${bulkQuery}&limit=50`)
          toast(`Queued ${r.queued} audit(s)${r.skipped_already_waiting ? `, ${r.skipped_already_waiting} already waiting` : ''}`)
          if (r.queued) location.hash = `#/results/${r.run}` // watch them finish on Audit Results
        } catch (err) { toast(err.message, 'bad') }
      } }, icon('bolt', 14), 'Full audit for these leads') : null
    const assignTo = picked ? h('select', { class: 'small-select', 'aria-label': 'Give the picked leads to' },
      h('option', { value: '', text: 'Give picked to…' }), active.map((t) => h('option', { value: t.id, text: t.name })), h('option', { value: 'none', text: '— nobody (unassign)' })) : null
    if (assignTo) assignTo.onchange = () => { const v = assignTo.value; if (v) assignPicked(v === 'none' ? null : Number(v)) }
    const pickAll = picked ? h('input', { type: 'checkbox', 'aria-label': 'Pick every lead on this page', onchange: (e) => {
      page.items.forEach((b) => (e.target.checked ? picked.add(b.id) : picked.delete(b.id)))
      list.querySelectorAll('tbody input, tr td input[type=checkbox]').forEach((c) => { c.checked = e.target.checked })
    } }) : null
    const from = page.total ? filters.offset + 1 : 0
    const to = Math.min(filters.offset + PAGE_SIZE, page.total)
    fill(list,
      h('div', { class: 'row-between' }, h('span', { class: 'mute small', text: `${from}–${to} of ${page.total} leads` }),
        h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center' }, assignTo, bulk,
          canExport ? h('a', { class: 'btn ghost small', href: exportUrl('xlsx') }, icon('download', 14), 'Excel') : null,
          canExport ? h('a', { class: 'btn ghost small', href: exportUrl('csv'), text: 'CSV' }) : null,
          h('button', { class: 'ghost small', disabled: filters.offset === 0, text: '← Prev', onclick: () => { filters.offset = Math.max(0, filters.offset - PAGE_SIZE); load() } }),
          h('button', { class: 'ghost small', disabled: to >= page.total, text: 'Next →', onclick: () => { filters.offset += PAGE_SIZE; load() } }))),
      page.items.length ? h('table', { class: 'rows-in' },
        h('tr', {}, picked ? h('th', {}, pickAll) : null,
          ...['Score', 'Business', 'Phone', 'City · area', 'Owner', 'Website', 'Added'].map((t) => h('th', { text: t }))),
        page.items.map((b, i) => leadRow(b, i, team, picked, (id, on) => (on ? picked.add(id) : picked.delete(id)))))
        : h('div', { class: 'empty' }, icon('leads'), h('div', { text: filters.audit === 'audited'
          ? 'No audited leads match yet. Run a full audit from the “Not audited yet” tab.'
          : 'No un-audited leads match. Collect more in Lead Search, or see the “Audited” tab.' })))
  }

  const reload = () => { filters.offset = 0; load() }
  const later = (key) => (e) => { clearTimeout(typing); filters[key] = e.target.value.trim(); typing = setTimeout(reload, 300) }
  const owners = [['', 'Anyone'], ['any', 'Assigned (to someone)'], ['none', 'Unassigned'], [String(user.id), 'Me'],
    ...active.filter((t) => t.id !== user.id).map((t) => [String(t.id), t.name])]
  const page = h('div', {},
    pageHead('All Leads', 'New and audited leads are kept apart, so a bulk audit never repeats a business.'),
    ownerBar,
    splitBox,
    tabs,
    h('div', { class: 'card filters' },
      h('div', {}, h('label', { text: 'Countries (none ticked = all countries)' }),
        h('div', { class: 'chips' }, Object.entries(m.countries).map(([cc, c]) => chip(c.name, cc, filters.country.has(cc), (e) => {
          if (e.target.checked) filters.country.add(cc); else filters.country.delete(cc)
          reload()
        })))),
      h('div', { class: 'row' },
        h('div', { class: 'grow' }, h('label', {}, 'Search name / phone / website', h('input', { type: 'search', value: filters.q, placeholder: 'e.g. dental', oninput: later('q') }))),
        h('div', {}, h('label', {}, 'City', h('input', { value: filters.city, placeholder: 'any', oninput: later('city') }))),
        h('div', {}, h('label', {}, 'Industry', select([['', 'All'], ...Object.entries(m.industries).map(([k, v]) => [k, v.label])], filters.industry,
          (e) => { filters.industry = e.target.value; reload() }))),
        h('div', {}, h('label', {}, 'Owner', select(owners, filters.owner, (e) => { filters.owner = e.target.value; reload() }))),
        h('div', {}, h('label', {}, 'Sort', select([['newest', 'Newest first'], ['score', 'Highest score first']], filters.sort,
          (e) => { filters.sort = e.target.value; reload() }))))),
    list)
  reveal(page)
  fill(root, page)
  await load()
  return () => clearTimeout(typing)
}
