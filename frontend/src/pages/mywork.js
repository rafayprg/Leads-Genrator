import { api } from '../api.js'
import { badge, fill, h, icon, pageHead, reveal, salesBadge, statTile } from '../ui.js'
import { scoreRing } from './overview.js'

function leadRow(x, i) {
  return h('li', { style: `--i:${i}` },
    h('span', { style: 'display:flex;gap:12px;align-items:center;min-width:0' }, scoreRing(x.score),
      h('span', { style: 'min-width:0' }, h('a', { href: `#/leads/${x.id}/pitch`, text: x.name }),
        h('div', { class: 'small mute', text: [x.business_id, x.industry, x.city].filter(Boolean).join(' · ') }))),
    h('span', { style: 'display:flex;gap:8px;align-items:center' }, x.sales ? salesBadge(x.sales) : (x.audited ? null : badge('not audited', 'ghost')),
      x.phone ? h('a', { class: 'btn ghost small', href: `tel:${x.phone}`, 'aria-label': `Call ${x.name}` }, icon('phone', 14)) : null))
}

const list = (title, items, empty, extra = '') => h('section', { class: 'card' },
  h('div', { class: 'section-title' }, h('h2', { text: title }), items.length ? badge(String(extra || items.length)) : null),
  items.length ? h('ul', { class: 'list-plain' }, items.map(leadRow)) : h('p', { class: 'small mute', text: empty }))

/** My work: one salesperson's day — what to call next, follow-ups due, own leads. */
export async function mywork(root, user) {
  const w = await api.get('/me/work')
  const pct = w.daily_call_target ? Math.min(100, Math.round((100 * w.calls_today) / w.daily_call_target)) : 0
  const next = w.next
  fill(root, reveal(h('div', {},
    pageHead(`${user.name.split(' ')[0]}'s day`, 'Your follow-ups first, then your best leads nobody has called yet.'),
    h('div', { class: 'grid' },
      statTile('Calls today', `${w.calls_today} / ${w.daily_call_target}`, { ico: 'phone', hint: `${pct}% of your daily target` }),
      statTile('Calls this week', w.calls_week, { ico: 'activity', tone: 'cyan' }),
      statTile('Won this week', w.won_week, { ico: 'results', tone: w.won_week ? '' : 'amber' }),
      statTile('My leads', w.owned, { ico: 'leads', hint: `${w.to_call_total} not called yet` })),
    h('div', { class: 'bar', style: 'margin:-6px 0 18px' }, h('i', { style: `width:${pct}%` })),
    next ? h('section', { class: 'card next-call' },
      h('div', { class: 'section-title' }, h('h2', { text: next.sales?.status === 'follow_up' ? 'Next: a follow-up that is due' : 'Next best lead to call' }), salesBadge(next.sales)),
      h('div', { style: 'display:flex;gap:16px;align-items:center;flex-wrap:wrap' }, scoreRing(next.score, next.band),
        h('div', { style: 'flex:1;min-width:200px' }, h('div', { class: 'big', text: next.name }), h('div', { class: 'small mute', text: [next.industry, next.city].filter(Boolean).join(' · ') })),
        h('a', { class: 'btn', href: `#/leads/${next.id}/pitch` }, 'Open pitch', icon('arrow', 14)),
        next.phone ? h('a', { class: 'btn ghost', href: `tel:${next.phone}` }, icon('phone', 15), next.phone) : null))
      : h('section', { class: 'card empty' }, icon('leads'), h('div', { text: w.owned
        ? 'Nothing due and every lead of yours has been called. Take more from All Leads.'
        : 'No leads are yours yet. An admin can assign some (Team → Auto-assign), or take unowned ones from a lead page.' })),
    h('div', { class: 'grid two' },
      list('Follow-ups due', w.follow_ups, 'No follow-up is due today.'),
      list('To call', w.to_call, 'Every lead of yours has been called.', w.to_call_total)),
    w.in_progress.length ? list('In progress', w.in_progress, '') : null)))
}
