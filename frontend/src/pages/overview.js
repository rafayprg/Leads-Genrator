import { api, meta } from '../api.js'
import { badge, banner, barList, countUp, fill, h, icon, money, pageHead, reveal, statTile, statusBadge, toast, when } from '../ui.js'

const RANK = { viewer: 0, sales: 1, admin: 2 }

export function scoreRing(score, band) {
  const tone = score >= 80 ? 'var(--acc)' : score >= 60 ? 'var(--acc2)' : score >= 40 ? 'var(--warn)' : 'var(--faint)'
  return h('span', { class: 'score' }, h('span', { class: 'ring', style: `--p:${score ?? 0};--ring:${tone}`, text: score ?? '—' }),
    band ? h('span', { class: 'small mute', text: band }) : null)
}

function greeting(name) {
  const hr = new Date().getHours()
  const part = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening'
  return `${part}, ${(name || '').split(' ')[0] || 'there'}`
}

function funnel(steps) {
  const top = Math.max(steps[0][1], 1)
  return h('div', { class: 'funnel' }, steps.map(([label, n], i) => {
    const prev = i ? steps[i - 1][1] : null
    return h('div', { class: 'fstep', style: `--i:${i}` },
      h('div', { class: 'fl', text: label }), h('div', { class: 'fn' }, countUp(n)),
      h('div', { class: 'fp', text: prev === null ? 'all collected leads' : prev ? `${Math.round((100 * n) / prev)}% of previous step` : '—' }),
      h('i', { class: 'fbar', style: `--w:${Math.max(4, (100 * n) / top)}%` }))
  }))
}

/** @param {HTMLElement} root */
export async function overview(root, user) {
  const canSales = RANK[user?.role] >= RANK.sales
  const [s, m, sales, stale, top, audited] = await Promise.all([api.get('/stats'), meta(), api.get('/sales/summary'),
    api.get('/audits/stale'), api.get('/results?sort=score&limit=6'), api.get('/businesses?audit=audited&limit=1')])
  const by = sales.by_status
  const contacted = Object.values(by).reduce((a, b) => a + b, 0)
  const warm = (by.interested || 0) + (by.follow_up || 0) + (by.won || 0)
  const due = sales.follow_ups_due

  const reaudit = h('button', { class: 'ghost small', disabled: !stale.count || !canSales, onclick: async (e) => {
    e.currentTarget.disabled = true
    const r = await api.post('/audits/reaudit-stale')
    toast(`Re-audit started for ${r.queued} lead(s)`)
    if (r.run) location.hash = `#/results/${r.run}`
  } }, icon('refresh', 14), 'Re-audit')

  const body = h('div', {},
    pageHead(greeting(user?.name), 'Where your leads stand today: collected, audited, called and won.',
      RANK[user?.role] >= RANK.admin ? h('a', { class: 'btn ghost', href: '#/search' }, icon('search', 15), 'Find leads') : null,
      h('a', { class: 'btn', href: '#/results' }, 'Audit results', icon('arrow', 15))),
    s.apify.accounts ? null : banner('warn', 'No Apify account yet, so no new leads can be collected. Add one in ', h('a', { href: '#/settings', text: 'Settings' }), '.'),
    h('div', { class: 'grid' },
      statTile('Leads collected', s.businesses, { ico: 'leads' }),
      statTile('Audited', audited.total, { ico: 'results', tone: 'cyan', hint: `${s.businesses - audited.total} still waiting` }),
      statTile('Follow-ups due', due.length, { ico: 'calendar', tone: due.length ? 'amber' : '', hint: 'today or earlier' }),
      statTile('Apify credit left', Number(s.apify.credit_left_usd || 0), { ico: 'bolt', tone: 'cyan', prefix: '$', decimals: 2,
        hint: `${s.apify.accounts} account${s.apify.accounts === 1 ? '' : 's'}` }),
      statTile('Failed agent tasks', s.failed_tasks, { ico: 'monitor', tone: s.failed_tasks ? 'rose' : '', hint: s.failed_tasks ? 'see Agent Monitor' : 'all clear' })),
    h('section', { class: 'card' }, h('div', { class: 'section-title' }, h('h2', { text: 'Pipeline' }),
      h('span', { class: 'small mute', text: 'interested = interested + follow-up + won' })),
    funnel([['Leads', s.businesses], ['Audited', audited.total], ['Contacted', contacted], ['Interested', warm], ['Won', by.won || 0]])),
    h('div', { class: 'grid two' },
      h('section', { class: 'card' }, h('div', { class: 'section-title' }, h('h2', { text: 'Best opportunities' }),
        h('a', { class: 'small', href: '#/results', text: 'All results →' })),
      top.results.length ? h('ul', { class: 'list-plain' }, top.results.map((r) => h('li', {},
        h('span', { style: 'display:flex;gap:12px;align-items:center;min-width:0' }, scoreRing(r.score),
          h('span', { style: 'min-width:0' }, h('a', { href: `#/leads/${r.business_pk}`, text: r.name }),
            h('div', { class: 'small mute', text: [r.industry, r.city].filter(Boolean).join(' · ') }))),
        h('span', {}, r.sales ? badge(r.sales.status.replace('_', ' '), 'run') : badge('not called', 'ghost')))))
        : h('div', { class: 'empty' }, icon('results'), h('div', { text: 'No audits yet. Run one from All Leads.' }))),
      h('div', {},
        h('section', { class: 'card' }, h('div', { class: 'section-title' }, h('h2', { text: 'Follow-ups due' }), due.length ? badge(String(due.length), 'warn') : null),
          due.length ? h('ul', { class: 'list-plain' }, due.slice(0, 8).map((d) => h('li', {}, h('a', { href: `#/leads/${d.business_pk}`, text: d.name }), icon('phone', 14))))
            : h('p', { class: 'mute small', text: 'Nothing due. Calls you mark “Follow-up” with a date show up here.' })),
        h('section', { class: 'card' }, h('div', { class: 'section-title' }, h('h2', { text: 'Stale audits' }), reaudit),
          h('p', { class: 'small mute', text: stale.count
            ? `${stale.count} lead(s) were audited more than ${stale.days} days ago — their websites may have changed.`
            : `Every audit is younger than ${stale.days} days.` })))),
    h('div', { class: 'grid wide' },
      h('section', { class: 'card' }, h('h2', { text: 'Leads by country' }), h('div', { class: 'gap' },
        barList(Object.entries(s.by_country).map(([cc, n]) => [m.countries[cc]?.name || cc, n]).sort((a, b) => b[1] - a[1]), 'No leads yet'))),
      h('section', { class: 'card' }, h('h2', { text: 'Leads by industry' }), h('div', { class: 'gap' },
        barList(Object.entries(s.by_industry).map(([k, n]) => [m.industries[k]?.label || k, n]).sort((a, b) => b[1] - a[1]).slice(0, 8), 'No leads yet')))),
    h('section', { class: 'card wrap' }, h('h2', { text: 'Recent searches' }),
      h('table', { class: 'rows-in' }, h('tr', {}, ...['When', 'Where', 'Status', 'New leads', 'Apify $'].map((t, i) => h('th', { class: i > 2 ? 'num' : '', text: t }))),
        s.searches.length ? s.searches.map((r, i) => h('tr', { style: `--r:${i}` },
          h('td', { class: 'mute small', text: when(r.created_at) }),
          h('td', { text: r.targets.map((t) => t[1]).join(', ') + ' · ' + r.industries.join(', ') }),
          h('td', {}, statusBadge(r.status)),
          h('td', { class: 'num', text: r.new_businesses }),
          h('td', { class: 'num', text: money(r.spent_usd) }))) : h('tr', {}, h('td', { class: 'mute', colspan: 5, text: 'No searches yet — start one in Lead Search.' })))))
  reveal(body)
  fill(root, body)
}
