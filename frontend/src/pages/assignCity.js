import { api, meta } from '../api.js'
import { SALES_STATES, badge, fill, h, icon, pageHead, reveal, statTile, toast } from '../ui.js'

const LABEL = Object.fromEntries([['pending', 'Pending'], ...SALES_STATES.map(([k, l]) => [k, l])])

function funnelCard(f) {
  const order = ['pending', 'connected', 'not_connected', 'interested', 'follow_up', 'not_interested', 'not_on_whatsapp', 'won']
  const max = Math.max(1, ...order.map((k) => f.by_status[k] || 0))
  return h('section', { class: 'card' }, h('h2', { text: 'Call funnel (assigned leads)' }),
    h('ul', { class: 'list-plain' }, order.map((k) => h('li', {},
      h('span', { style: 'min-width:130px', text: LABEL[k] }),
      h('div', { class: 'bar', style: 'flex:1;margin:0 10px' }, h('i', { style: `width:${(100 * (f.by_status[k] || 0)) / max}%` })),
      h('b', { text: String(f.by_status[k] || 0) })))))
}

function membersCard(f) {
  return h('section', { class: 'card' }, h('h2', { text: 'Team on the phones' }),
    f.members.length ? h('table', {}, h('tr', {}, ...['Member', 'Leads', 'Called', 'Reached', 'Hot', 'Hot rate'].map((t, i) => h('th', { class: i ? 'num' : '', text: t }))),
      f.members.map((m) => h('tr', {}, h('td', {}, h('a', { href: `#/calls?who=${m.id}`, text: m.name })),
        h('td', { class: 'num', text: m.leads }), h('td', { class: 'num', text: m.called }), h('td', { class: 'num', text: m.reached }),
        h('td', { class: 'num', text: m.hot }), h('td', { class: 'num', text: m.hot_rate == null ? '—' : `${m.hot_rate}%` }))))
      : h('p', { class: 'small mute', text: 'Nobody has leads yet. Assign a city below.' }))
}

/** Calling desk for the admin: funnel, team workload, and handing out leads city by city. */
export async function assignCity(root, user) {
  const [m, team] = await Promise.all([meta(), api.get('/team')])
  const members = team.filter((t) => t.is_active && t.role !== 'viewer')
  const canAssign = user.role === 'admin'
  const filters = { country: '', industry: '' }
  const top = h('div')
  const table = h('div')
  const country = h('select', { onchange: (e) => { filters.country = e.target.value; load() } },
    h('option', { value: '', text: 'All countries' }), Object.entries(m.countries).map(([cc, c]) => h('option', { value: cc, text: c.name })))
  const industry = h('select', { onchange: (e) => { filters.industry = e.target.value; load() } },
    h('option', { value: '', text: 'All industries' }), Object.entries(m.industries).map(([k, v]) => h('option', { value: k, text: v.label })))

  function row(r) {
    const who = h('select', { 'aria-label': `Give ${r.city} to` }, h('option', { value: '', text: 'Pick member…' }),
      members.map((t) => h('option', { value: t.id, text: t.name })))
    const howMany = h('input', { type: 'number', min: 1, max: r.unassigned || 1, placeholder: `all ${r.unassigned}`, style: 'width:90px', 'aria-label': 'How many' })
    const give = async () => {
      if (!who.value) return toast('Pick a team member', 'bad')
      try {
        const res = await api.post('/calling/assign-city', { country: r.country, city: r.city, user_id: Number(who.value),
          industry: filters.industry || null, limit: Number(howMany.value) || null })
        toast(`${res.assigned} ${r.city} leads given to ${who.selectedOptions[0].text}`)
        load()
      } catch (err) { toast(err.message, 'bad') }
    }
    const back = async () => {
      if (!confirm(`Take every assigned ${r.city} lead back to the pool? Call history stays on each lead.`)) return
      const res = await api.post('/calling/assign-city', { country: r.country, city: r.city, user_id: null, industry: filters.industry || null })
      toast(`${res.assigned} leads back in the pool`); load()
    }
    return h('tr', {},
      h('td', {}, h('b', { text: r.city }), h('div', { class: 'small mute', text: m.countries[r.country]?.name || r.country })),
      h('td', { class: 'num', text: r.total }), h('td', { class: 'num' }, r.unassigned ? badge(String(r.unassigned), 'warn') : '0'),
      h('td', { class: 'small' }, r.owners.length ? r.owners.map((o) => `${o.name} ${o.leads}`).join(' · ') : h('span', { class: 'mute', text: 'nobody' })),
      canAssign ? h('td', {}, h('div', { class: 'row gap', style: 'flex-wrap:wrap' }, who, howMany,
        h('button', { class: 'small', disabled: !r.unassigned, onclick: give }, icon('arrow', 14), 'Assign'),
        r.owners.length ? h('button', { class: 'ghost small', onclick: back, text: 'Take back' }) : null)) : null)
  }

  async function load() {
    const p = new URLSearchParams()
    if (filters.country) p.set('country', filters.country)
    if (filters.industry) p.set('industry', filters.industry)
    const [rows, f] = await Promise.all([api.get(`/calling/cities?${p}`), api.get('/calling/funnel')])
    fill(top, h('div', { class: 'grid' },
      statTile('Assigned', f.assigned, { ico: 'leads' }), statTile('In the pool', f.unassigned, { ico: 'search', tone: 'amber' }),
      statTile('Hot', (f.by_status.interested || 0) + (f.by_status.follow_up || 0), { ico: 'results', tone: 'cyan' }),
      statTile('Won', f.by_status.won || 0, { ico: 'bolt' })),
    h('div', { class: 'grid two' }, funnelCard(f), membersCard(f)))
    fill(table, rows.length ? h('table', { class: 'hover' },
      h('tr', {}, ...['City', 'Leads', 'Unassigned', 'Who has them', canAssign ? 'Give to' : null].filter(Boolean).map((t, i) => h('th', { class: i && i < 3 ? 'num' : '', text: t }))),
      rows.map(row)) : h('p', { class: 'mute small', text: 'No leads for this filter. Run a Lead Search first.' }))
  }

  fill(root, reveal(h('div', {},
    pageHead('Calling desk', 'Hand leads to the team city by city, and see how the calls are going.'),
    top,
    h('section', { class: 'card' }, h('h2', { text: 'Assign by city' }),
      h('p', { class: 'small mute', text: 'Only unassigned leads are given, best audit score first. Leave "how many" empty to give the whole city.' }),
      h('div', { class: 'row gap' }, h('div', {}, h('label', {}, 'Country', country)), h('div', {}, h('label', {}, 'Industry', industry))),
      h('div', { class: 'gap wrap' }, table)))))
  await load()
}
