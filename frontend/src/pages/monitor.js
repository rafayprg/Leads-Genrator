import { api } from '../api.js'
import { badge, banner, fill, h, pageHead, reveal, statTile, when } from '../ui.js'

const REFRESH_MS = 3000
const AGENTS = [
  ['website_expert', 'Agent 1 · Website'], ['social_media_finder', 'Agent 3 · Social finder'],
  ['social_media_expert', 'Agent 2 · Social'], ['automation_runner', 'Agent 4 · Automation'],
  ['data_organizer', 'Agent 5 · Organizer'], ['reporting', 'Agent 6 · Reports'], ['main', 'Main Agent · final step'],
]
const STATES = ['pending', 'running', 'completed', 'skipped', 'failed']

function taskTable(rows, extra) {
  return h('table', {}, h('tr', {}, ...['Agent', 'Business', 'Attempts', 'Detail', ''].map((t) => h('th', { text: t }))),
    rows.map((r) => h('tr', {},
      h('td', { text: (AGENTS.find(([k]) => k === r.agent) || [, r.agent])[1] }),
      h('td', {}, h('a', { href: `#/leads/${r.business_pk}`, text: `${r.business_id} ${r.business}` })),
      h('td', { class: 'num', text: r.attempts }),
      h('td', { class: 'small mute', text: extra(r) }),
      h('td', {}, r.retryable ? h('button', { class: 'ghost', text: 'Retry', onclick: async (e) => {
        e.target.disabled = true
        await api.post(`/tasks/${r.task_id}/retry`)
      } }) : null))))
}

/** @param {HTMLElement} root */
export async function monitor(root) {
  const body = h('div')
  let timer = null

  async function load() {
    clearTimeout(timer)
    try {
      const m = await api.get('/monitor')
      const alive = m.workers.threads.filter((t) => t.alive).length
      fill(body,
        h('div', { class: 'grid' },
          statTile('Worker threads alive', `${alive}/${m.workers.threads.length}`, { ico: 'monitor', tone: alive ? '' : 'rose' }),
          statTile('Running now', m.running.length ? h('span', { class: 'live', style: 'font-size:28px', text: String(m.running.length) }) : '0', { ico: 'bolt', tone: 'cyan' }),
          statTile('Ready to start', String(m.ready_now), { ico: 'results' }),
          statTile('Waiting to retry', String(m.retrying.length), { ico: 'refresh', tone: m.retrying.length ? 'amber' : '' }),
          statTile('Failed (recent)', String(m.failed.length), { ico: 'shield', tone: m.failed.length ? 'rose' : '' })),
        h('div', { class: 'card wrap' }, h('b', { text: 'Tasks per agent' }),
          h('table', {}, h('tr', {}, h('th', { text: 'Agent' }), ...STATES.map((s) => h('th', { text: s }))),
            AGENTS.map(([k, label]) => h('tr', {}, h('td', { text: label }),
              ...STATES.map((s) => h('td', { class: 'num' }, m.agents[k]?.[s] ? badge(String(m.agents[k][s]),
                { failed: 'bad', running: 'run', completed: 'ok' }[s] || '') : '·')))))),
        h('div', { class: 'card wrap' }, h('b', { text: 'Running now' }),
          m.running.length ? taskTable(m.running, (r) => `started ${when(r.started_at)}`) : h('p', { class: 'mute', text: 'Nothing running.' }),
          h('p', { class: 'small mute', text: `Heavy agents run one at a time: ${Object.keys(m.workers.limits).join(', ')}.` })),
        m.retrying.length ? h('div', { class: 'card wrap' }, h('b', { text: 'Waiting to retry' }),
          taskTable(m.retrying, (r) => `${r.error || ''} · next try ${r.retry_after ? when(r.retry_after) : 'soon'}`)) : null,
        h('div', { class: 'card wrap' }, h('b', { text: 'Failed — after all attempts' }),
          m.failed.length ? taskTable(m.failed.map((r) => ({ ...r, retryable: true })), (r) => r.error || '')
            : h('p', { class: 'ok', text: 'No failed tasks.' })),
        h('p', { class: 'small mute', text: `Audits by status: ${Object.entries(m.jobs).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none yet'}. Refreshes every 3 s.` }),
      )
    } catch (err) {
      fill(body, banner('bad', err.message))
    }
    timer = setTimeout(load, REFRESH_MS)
  }

  fill(root, reveal(h('div', {}, pageHead('Agent Monitor', 'What every agent is doing, what is waiting, and what failed. One failure never stops the rest of an audit.'),
    body)))
  await load()
  return () => clearTimeout(timer)
}
