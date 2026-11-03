import { api } from '../api.js'
import { fill, h, pageHead, reveal, when } from '../ui.js'

/** Admin: who did what and when (logins, searches, audits, exports, settings). */
export async function activity(root) {
  const rows = await api.get('/activity?limit=300')
  fill(root, reveal(h('div', {},
    pageHead('Activity log', 'Every login, search, audit, export and settings change. Keys are never stored here, only their last 4 characters.'),
    h('div', { class: 'card wrap' }, h('table', { class: 'rows-in' },
      h('tr', {}, ...['When', 'Who', 'What', 'On', 'Details', 'IP'].map((t) => h('th', { text: t }))),
      rows.length ? rows.map((a, i) => h('tr', { style: `--r:${i}` },
        h('td', { class: 'small mute', text: when(a.at) }),
        h('td', { text: a.user || '—' }),
        h('td', {}, h('span', { class: `tag ${a.action.includes('failed') ? 'bad' : ''}`, text: a.action.replaceAll('_', ' ') })),
        h('td', { class: 'small', text: a.target || '' }),
        h('td', { class: 'small mute', text: Object.keys(a.detail || {}).length ? JSON.stringify(a.detail) : '' }),
        h('td', { class: 'small mute', text: a.ip || '' })))
        : h('tr', {}, h('td', { class: 'mute', text: 'Nothing yet.' })))))))
}
