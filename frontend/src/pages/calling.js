import { api } from '../api.js'
import { SALES_STATES, badge, banner, fill, h, icon, pageHead, reveal, salesBadge, toast, when } from '../ui.js'

// the calling desk's own buttons (older statuses still show as badges)
const DESK = SALES_STATES.filter(([k]) => !['called', 'no_answer'].includes(k))
const TABS = [['', 'All'], ['pending', 'Pending'], ...DESK.map(([k, label]) => [k, label])]
const digits = (p) => (p || '').replace(/\D/g, '')

function leadCard(x, onSaved, linkLead) {
  const note = h('input', { placeholder: 'Note (optional)', maxlength: 2000, 'aria-label': `Note for ${x.name}` })
  const due = h('input', { type: 'date', 'aria-label': 'Follow-up date', hidden: true })
  const pick = h('div', { class: 'status-pick', role: 'group', 'aria-label': 'Call outcome' }, DESK.map(([k, label]) =>
    h('button', { type: 'button', class: `ghost small ${x.status === k ? 'on' : ''}`, text: label, onclick: async () => {
      if (k === 'follow_up' && !due.value) { due.hidden = false; due.focus(); toast('Pick a follow-up date, then press Follow-up again', 'bad'); return }
      try {
        await api.post(`/businesses/${x.id}/sales`, { status: k, note: note.value.trim() || null, follow_up_on: k === 'follow_up' ? due.value : null })
        toast(`${x.name}: ${label}`)
        onSaved()
      } catch (err) { toast(err.message, 'bad') }
    } })))
  const wa = digits(x.whatsapp || x.phone)
  return h('article', { class: 'card call-card' },
    h('div', { class: 'section-title' },
      h('div', { style: 'min-width:0' }, linkLead ? h('a', { href: `#/leads/${x.id}/pitch`, class: 'big', text: x.name }) : h('div', { class: 'big', text: x.name }),
        h('div', { class: 'small mute', text: [x.category || x.industry, x.area, x.city].filter(Boolean).join(' · ') })),
      x.status === 'pending' ? badge('Pending', 'ghost') : salesBadge(x.last)),
    h('div', { class: 'row gap', style: 'flex-wrap:wrap;align-items:center' },
      x.phone ? h('a', { class: 'btn small', href: `tel:${x.phone}` }, icon('phone', 14), x.phone) : badge('no phone', 'ghost'),
      wa ? h('a', { class: 'btn ghost small', href: `https://wa.me/${wa}`, target: '_blank', rel: 'noopener' }, 'WhatsApp') : null,
      x.website ? h('a', { class: 'btn ghost small', href: x.website, target: '_blank', rel: 'noopener' }, 'Website') : null,
      x.maps_url ? h('a', { class: 'btn ghost small', href: x.maps_url, target: '_blank', rel: 'noopener' }, 'Map') : null,
      x.rating ? h('span', { class: 'small mute', text: `${x.rating}★ (${x.review_count || 0})` }) : null,
      x.score != null ? h('span', { class: 'small mute', text: `score ${x.score}` }) : null),
    x.last?.note ? h('p', { class: 'small mute', text: `Last note (${when(x.last.at)}): ${x.last.note}` }) : null,
    h('div', { class: 'gap' }, pick, h('div', { class: 'row gap' }, note, due)))
}

/** My calls: one member's leads with the call buttons. An admin can switch to anyone's list. */
export async function calling(root, user) {
  const isAdmin = user.role === 'admin'
  const team = isAdmin ? await api.get('/team') : []
  const asked = Number(new URLSearchParams(location.hash.split('?')[1] || '').get('who'))
  const state = { who: isAdmin && asked ? asked : user.id, status: '', city: '' }
  const tabs = h('div', { class: 'tabs', role: 'tablist' })
  const box = h('div')
  const head = h('div')
  const citySel = h('select', { 'aria-label': 'City', onchange: (e) => { state.city = e.target.value; load() } })
  const whoSel = isAdmin ? h('select', { 'aria-label': 'Team member', onchange: (e) => { state.who = Number(e.target.value); state.city = ''; load() } },
    team.filter((t) => t.is_active).map((t) => h('option', { value: t.id, text: t.id === user.id ? `${t.name} (me)` : t.name, selected: t.id === state.who }))) : null

  async function load() {
    const p = new URLSearchParams()
    if (state.who !== user.id) p.set('user_id', state.who)
    if (state.status) p.set('status', state.status)
    if (state.city) p.set('city', state.city)
    const r = await api.get(`/calling/list?${p}`)
    fill(citySel, h('option', { value: '', text: `All cities (${r.cities.length})` }),
      r.cities.map((c) => h('option', { value: c, text: c || '(no city)', selected: c === state.city })))
    fill(tabs, TABS.map(([k, label]) => h('button', { type: 'button', role: 'tab', class: `tab ${state.status === k ? 'on' : ''}`,
      'aria-selected': String(state.status === k), onclick: () => { state.status = k; load() } },
    label, h('span', { class: 'count-pill', text: String(k ? (r.counts[k] || 0) : r.total) }))))
    fill(head, banner('', `${r.total} leads assigned · ${r.counts.pending || 0} not called yet · ${(r.counts.interested || 0) + (r.counts.follow_up || 0)} hot`))
    fill(box, r.items.length ? h('div', { class: 'grid two' }, r.items.map((x) => leadCard(x, load, user.role !== 'caller')))
      : h('section', { class: 'card empty' }, icon('leads'), h('div', { text: r.total
        ? 'No lead with this status here.'
        : 'No leads assigned yet. An admin hands them out city by city in Calling → Assign by city.' })))
  }

  fill(root, reveal(h('div', {},
    pageHead('My calls', 'Your assigned leads. Call or WhatsApp, then press the outcome — it is saved on the lead for everyone.'),
    h('div', { class: 'row gap', style: 'align-items:end;flex-wrap:wrap' },
      whoSel ? h('div', {}, h('label', {}, 'Team member', whoSel)) : null, h('div', {}, h('label', {}, 'City', citySel))),
    head, tabs, box)))
  await load()
}
