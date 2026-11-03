import { api } from '../api.js'
import { badge, banner, fill, h, safeLink, statusBadge, when } from '../ui.js'

const POLL_MS = 3000
const CONF_KIND = { high: 'ok', medium: 'warn', low: 'bad' }
const STATUS_TEXT = { probable: 'likely official', requires_review: 'check by hand', unverified: 'not checked yet' }

/** Social profiles block (Agent 3) for one business. Returns { el, stop }. */
export function socialSection(b) {
  const el = h('div', { class: 'card' })
  let timer = null

  async function start(btn) {
    btn.disabled = true
    try {
      await api.post(`/businesses/${b.id}/social`)
    } catch (err) {
      el.prepend(banner('bad', err.message))
    }
    load()
  }

  async function load() {
    clearTimeout(timer)
    const a = await api.get(`/businesses/${b.id}/social`)
    const running = a.task_status === 'pending' || a.task_status === 'running'
    const s = a.summary
    const checked = a.profiles.filter((p) => p.last_checked_at)
    const unchecked = a.profiles.filter((p) => !p.last_checked_at)
    const row = (p) => h('tr', {},
      h('td', { text: p.platform }),
      h('td', {}, safeLink(p.profile_url, p.username || p.profile_url)),
      h('td', {}, badge(`${p.confidence}`, CONF_KIND[p.confidence] || ''), ' ',
        badge(STATUS_TEXT[p.verification_status] || p.verification_status)),
      h('td', { class: 'small mute' }, (p.evidence || []).join(' · ')))
    fill(el,
      h('div', { class: 'row-between' }, h('b', { text: 'Social profiles (Agent 3)' }),
        h('span', {}, a.task_status ? statusBadge(a.task_status) : null, ' ',
          h('button', { text: s ? 'Check again' : 'Find social profiles', disabled: running, onclick: (e) => start(e.target) }))),
      h('p', { class: 'small mute', text: 'Looks only at the business’s own website (home, contact, about) and links already on record. It does not search inside Instagram/Facebook.' }),
      running ? h('p', { class: 'mute', text: 'Agent 3 is reading the website…' }) : null,
      a.error ? banner('warn', `Last attempt had a problem: ${a.error}`) : null,
      checked.length ? h('table', {}, h('tr', {}, ...['Platform', 'Account', 'Confidence', 'Why'].map((t) => h('th', { text: t }))),
        checked.map(row)) : null,
      unchecked.length ? h('div', {}, h('p', { class: 'small mute', text: checked.length ? 'Collected but not checked yet:' : 'Collected links (not checked yet):' }),
        h('table', {}, unchecked.map(row))) : null,
      !a.profiles.length && s ? h('p', { class: 'mute', text: 'No social profiles found on the website.' }) : null,
      s ? h('p', { class: 'small mute' },
        s.platforms_not_found?.length ? `Not found: ${s.platforms_not_found.join(', ')}. ` : '',
        s.limitations?.length ? `Limits: ${s.limitations.join(' · ')}. ` : '',
        `Checked ${when(s.verification_timestamp)}.`) : null,
    )
    if (running) timer = setTimeout(load, POLL_MS)
  }

  load().catch((err) => el.replaceChildren(banner('bad', err.message)))
  return { el, stop: () => clearTimeout(timer) }
}
