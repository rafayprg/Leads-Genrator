import { api, meta } from '../api.js'
import { can, forget } from '../access.js'
import { badge, banner, chip, fill, h, icon, pageHead, reveal, toast, when } from '../ui.js'

const TABS = [['members', 'Members'], ['performance', 'Performance'], ['permissions', 'Permissions']]
const ROLES = [['caller', 'Caller (only My calls)'], ['sales', 'Sales'], ['admin', 'Admin'], ['viewer', 'Viewer (read only)']]
const initials = (name) => (name || '?').split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase()

function select(options, value) {
  return h('select', {}, options.map(([v, t]) => { const o = h('option', { value: v, text: t }); o.selected = v === value; return o }))
}

function chipsPick(m, kind, picked) {
  const set = new Set(picked || [])
  const items = kind === 'countries' ? Object.entries(m.countries).map(([k, c]) => [k, c.name]) : Object.entries(m.industries).map(([k, v]) => [k, v.label])
  const box = h('div', { class: 'chips' }, items.map(([k, label]) => chip(label, k, set.has(k), (e) => { if (e.target.checked) set.add(k); else set.delete(k) })))
  return { el: box, value: () => [...set] }
}

/** Add / edit form. `member` = null to add. Calls onDone(result). */
function memberForm(m, member, onDone, onCancel) {
  const f = {
    name: h('input', { value: member?.name || '', required: true }),
    email: h('input', { type: 'email', value: member?.email || '', required: true, disabled: Boolean(member) }),
    role: select(ROLES, member?.role || 'sales'),
    title: h('input', { value: member?.title || '', placeholder: 'e.g. Sales executive' }),
    phone: h('input', { value: member?.phone || '', placeholder: '+92 300 1234567' }),
    whatsapp: h('input', { value: member?.whatsapp || '', placeholder: 'same as phone?' }),
    target: h('input', { type: 'number', min: 0, max: 500, value: member?.daily_call_target ?? 30, style: 'width:100px' }),
  }
  const countries = chipsPick(m, 'countries', member?.countries)
  const industries = chipsPick(m, 'industries', member?.industries)
  const msg = h('div')
  const save = h('button', { type: 'submit', text: member ? 'Save changes' : 'Add member' })
  return h('form', { class: 'card member-form', onsubmit: async (e) => {
    e.preventDefault()
    save.disabled = true
    const body = { name: f.name.value.trim(), role: f.role.value, title: f.title.value.trim() || null, phone: f.phone.value.trim() || null,
      whatsapp: f.whatsapp.value.trim() || null, countries: countries.value(), industries: industries.value(), daily_call_target: Number(f.target.value) || 0 }
    try {
      const r = member ? await api.patch(`/team/${member.id}`, body) : await api.post('/team', { ...body, email: f.email.value.trim() })
      onDone(r)
    } catch (err) { msg.replaceChildren(banner('bad', err.message)); save.disabled = false }
  } },
    h('h2', { text: member ? `Edit ${member.name}` : 'Add a team member' }),
    h('div', { class: 'row gap' }, h('div', { class: 'grow' }, h('label', {}, 'Full name', f.name)), h('div', { class: 'grow' }, h('label', {}, 'Email (their login)', f.email)),
      h('div', {}, h('label', {}, 'Role', f.role))),
    h('div', { class: 'row gap' }, h('div', { class: 'grow' }, h('label', {}, 'Title', f.title)), h('div', { class: 'grow' }, h('label', {}, 'Phone', f.phone)),
      h('div', { class: 'grow' }, h('label', {}, 'WhatsApp', f.whatsapp)), h('div', {}, h('label', {}, 'Calls per day', f.target))),
    h('label', { class: 'gap', text: 'Countries they cover (none = all)' }), countries.el,
    h('label', { class: 'gap', text: 'Industries they cover (none = all)' }), industries.el,
    msg, h('div', { class: 'row gap' }, save, h('button', { type: 'button', class: 'ghost', text: 'Cancel', onclick: onCancel })))
}

function passwordBanner(name, pw) {
  return h('div', { class: 'banner ok' }, h('div', {},
    h('b', { text: `Temporary password for ${name}: ` }), h('code', { class: 'mono', text: pw }), ' ',
    h('button', { type: 'button', class: 'ghost small', onclick: async () => { try { await navigator.clipboard.writeText(pw); toast('Password copied') } catch { toast('Copy it by hand', 'bad') } } }, 'Copy'),
    h('div', { class: 'small', text: 'Shown only once. Give it to them privately; they must set their own password at first login.' })))
}

async function membersTab(user, m, box) {
  const isAdmin = user.role === 'admin'
  const assignAllowed = await can(user, 'assign_leads')
  const note = h('div')
  const formBox = h('div')
  async function draw() {
    const team = await api.get('/team')
    const active = team.filter((t) => t.is_active)
    const name = (cc) => cc.map((c) => m.countries[c]?.name || c).join(', ')
    const ind = (ks) => ks.map((k) => m.industries[k]?.label || k).join(', ')
    fill(box,
      h('div', { class: 'row-between' }, h('span', { class: 'small mute', text: `${active.length} active member(s) · ${team.length - active.length} left` }),
        h('span', { style: 'display:flex;gap:8px;flex-wrap:wrap' },
          assignAllowed ? h('button', { class: 'ghost', onclick: async (e) => {
            if (!confirm('Give every unassigned audited lead to a salesperson who covers its country and industry (fewest leads first)?')) return
            e.currentTarget.disabled = true
            try {
              const r = await api.post('/leads/auto-assign', { audit: 'audited' })
              note.replaceChildren(banner(r.assigned ? 'ok' : 'warn', r.assigned
                ? `Assigned ${r.assigned} of ${r.considered} lead(s): ${r.per_member.map((p) => `${p.name} ${p.leads}`).join(', ')}.`
                : `No lead assigned — ${r.considered ? 'nobody active covers those countries / industries' : 'no unassigned audited lead'}.`))
              draw()
            } catch (err) { note.replaceChildren(banner('bad', err.message)) }
          } }, icon('leads', 15), 'Auto-assign audited leads') : null,
          isAdmin ? h('button', { onclick: () => fill(formBox, memberForm(m, null, (r) => { forget(); fill(formBox); note.replaceChildren(passwordBanner(r.name, r.temp_password)); draw() }, () => fill(formBox))) },
            '+ Add member') : null)),
      note, formBox,
      h('div', { class: 'member-grid' }, team.map((t, i) => h('article', { class: `card member ${t.is_active ? '' : 'gone'}`, style: `--i:${i}` },
        h('div', { class: 'member-top' }, h('span', { class: 'avatar big-avatar', text: initials(t.name) }),
          h('div', { style: 'min-width:0' }, h('b', { text: t.name }), h('div', { class: 'small mute', text: t.title || t.email })),
          h('span', { class: 'member-tags' }, badge(t.role, t.role === 'admin' ? 'run' : t.role === 'sales' ? 'ok' : ''),
            !t.is_active ? badge('left', 'bad') : t.away ? badge('away', 'warn') : null, t.must_change_password && t.is_active ? badge('new — no login yet', 'ghost') : null)),
        h('dl', { class: 'kv small' },
          h('dt', { text: 'Covers' }), h('dd', { text: [t.countries.length ? name(t.countries) : 'All countries', t.industries.length ? ind(t.industries) : 'all industries'].join(' · ') }),
          t.phone ? [h('dt', { text: 'Phone' }), h('dd', {}, h('a', { href: `tel:${t.phone}`, text: t.phone }))] : null,
          h('dt', { text: 'Leads' }), h('dd', {}, h('a', { href: `#/leads?owner=${t.id}`, text: `${t.leads_owned} owned` })),
          h('dt', { text: 'Last login' }), h('dd', { text: t.last_login_at ? when(t.last_login_at) : 'never' })),
        isAdmin && t.id !== user.id ? h('div', { class: 'member-actions' },
          h('button', { class: 'ghost small', text: 'Edit', onclick: () => fill(formBox, memberForm(m, t, () => { fill(formBox); toast('Saved'); forget(); draw() }, () => fill(formBox))) }),
          t.is_active ? h('button', { class: 'ghost small', text: t.away ? 'Back from leave' : 'Mark away', onclick: async () => { await api.patch(`/team/${t.id}`, { away: !t.away }); draw() } }) : null,
          t.is_active ? h('button', { class: 'ghost small', text: 'Set PIN', onclick: async () => {
            const pin = prompt(`New login PIN for ${t.name} (4 to 8 digits). They pick their name on the login page's Team tab and type it.`)
            if (pin == null) return
            try { await api.put(`/team/${t.id}/pin`, { pin: pin.trim() }); toast(`PIN set for ${t.name}`) } catch (err) { toast(err.message, 'bad') }
          } }) : null,
          t.is_active ? h('button', { class: 'ghost small', text: 'Reset password', onclick: async () => {
            if (!confirm(`Give ${t.name} a new temporary password? Their old one stops working.`)) return
            const r = await api.patch(`/team/${t.id}`, { reset_password: true })
            note.replaceChildren(passwordBanner(t.name, r.temp_password)); draw()
          } }) : null,
          h('button', { class: t.is_active ? 'danger small' : 'ghost small', text: t.is_active ? 'Remove' : 'Bring back', onclick: async () => {
            if (t.is_active && !confirm(`Remove ${t.name}? They can no longer log in, and their ${t.leads_owned} lead(s) go back to the pool. Their calls stay in the history.`)) return
            try { await api.patch(`/team/${t.id}`, { is_active: !t.is_active }); forget(); draw() } catch (err) { toast(err.message, 'bad') }
          } })) : null))))
  }
  await draw()
}

async function performanceTab(box) {
  let days = 7
  async function draw() {
    const p = await api.get(`/team/performance?days=${days}`)
    const top = Math.max(...p.members.map((x) => x.calls), 1)
    fill(box,
      h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'Period' }, [[1, 'Today'], [7, '7 days'], [30, '30 days']].map(([d, label]) =>
        h('button', { type: 'button', role: 'radio', class: d === days ? 'on' : '', 'aria-checked': String(d === days), text: label, onclick: () => { days = d; draw() } }))),
      p.members.length ? h('div', { class: 'card wrap gap' }, h('table', { class: 'rows-in' },
        h('tr', {}, ...['#', 'Member', 'Calls', 'Today vs target', 'Interested+', 'Won', 'Hit rate', 'Leads', 'Due'].map((t, i) => h('th', { class: i > 1 ? 'num' : '', text: t }))),
        p.members.map((x, i) => h('tr', { style: `--r:${i}` },
          h('td', { class: 'mute', text: i + 1 }),
          h('td', {}, h('b', { text: x.name }), x.away ? badge('away', 'warn') : null, !x.active ? badge('left', 'bad') : null),
          h('td', { class: 'num' }, h('div', { class: 'mini-bar' }, h('i', { style: `width:${(100 * x.calls) / top}%` })), String(x.calls)),
          h('td', { class: 'num', text: `${x.calls_today} / ${x.daily_call_target}` }),
          h('td', { class: 'num', text: x.warm }), h('td', { class: 'num' }, x.won ? badge(String(x.won), 'won') : '0'),
          h('td', { class: 'num', text: x.hit_rate === null ? '—' : `${x.hit_rate}%` }),
          h('td', { class: 'num', text: x.leads_owned }), h('td', { class: 'num' }, x.follow_ups_due ? badge(String(x.follow_ups_due), 'warn') : '0')))),
      h('p', { class: 'small mute', text: 'Calls = every call outcome saved in the period. Interested+ = interested, follow-up and won. Hit rate = Interested+ ÷ calls.' }))
        : h('div', { class: 'card empty' }, h('div', { text: 'No sales or admin members yet.' })))
  }
  await draw()
}

async function permissionsTab(user, box) {
  const p = await api.get('/team/permissions')
  const isAdmin = user.role === 'admin'
  const boxes = {}
  fill(box, h('div', { class: 'card wrap' },
    h('table', {}, h('tr', {}, h('th', { text: 'What' }), ...Object.keys(p.roles).map((r) => h('th', { class: 'num', text: r })), h('th', { class: 'num', text: 'admin' })),
      Object.entries(p.labels).map(([k, label]) => h('tr', {}, h('td', { text: label }),
        ...Object.keys(p.roles).map((r) => {
          const c = h('input', { type: 'checkbox', disabled: !isAdmin, 'aria-label': `${r}: ${label}` })
          c.checked = p.roles[r][k]
          boxes[`${r}|${k}`] = c
          return h('td', { class: 'num' }, c)
        }), h('td', { class: 'num' }, badge('always', 'ok'))))),
    h('p', { class: 'small mute', text: 'Spending Apify credit, keys, limits and the team itself are always admin-only. Everyone can see all leads (your choice).' }),
    isAdmin ? h('button', { onclick: async () => {
      const body = {}
      for (const [key, c] of Object.entries(boxes)) { const [r, k] = key.split('|'); (body[r] ??= {})[k] = c.checked }
      try { await api.put('/team/permissions', body); forget(); toast('Permissions saved') } catch (err) { toast(err.message, 'bad') }
    } }, 'Save permissions') : null))
}

/** Team: members, performance, permissions (#/team/{tab}). */
export async function teamPage(root, user, tab = 'members') {
  const m = await meta()
  const active = TABS.some(([k]) => k === tab) ? tab : 'members'
  const box = h('div', { class: 'tab-body' })
  fill(root, reveal(h('div', {},
    pageHead('Team', 'Your sales team: who covers what, who owns which lead, and how the calls are going.'),
    h('nav', { class: 'tabs', 'aria-label': 'Team sections' }, TABS.map(([k, label]) =>
      h('a', { class: `tab ${k === active ? 'on' : ''}`, href: `#/team/${k}`, 'aria-current': k === active ? 'page' : null, text: label }))),
    box)))
  if (active === 'members') await membersTab(user, m, box)
  else if (active === 'performance') await performanceTab(box)
  else await permissionsTab(user, box)
}
