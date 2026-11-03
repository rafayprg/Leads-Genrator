import { api } from '../api.js'
import { banner, h, icon, money, fill, pageHead, reveal, toast, when } from '../ui.js'
import { aiCard, reportSettingsCard } from './aiSettings.js'

const LIMIT_TEXT = {
  apify_monthly_cap_usd: ['Apify spend per month (USD, all searches)', 0.5],
  apify_max_per_search_usd: ['Max Apify budget per search (USD)', 0.5],
  bulk_audit_max: ['Leads per "Full audit for these leads" click', 1],
  audits_per_day_max: ['Audits that can be started per day', 1],
  website_max_pages: ['Pages Agent 1 inspects per website', 1],
  website_max_links: ['Links Agent 1 tests per website', 1],
  task_max_attempts: ['Attempts per agent task before it fails', 1],
  task_stuck_minutes: ['Flag a task as stuck after (minutes)', 1],
  ai_calls_per_day_max: ['AI calls per day (Gemini / Groq free tier)', 1],
  audit_stale_days: ['An audit counts as stale after (days)', 1],
}

async function limitsCard(isAdmin) {
  const msg = h('div')
  const lim = await api.get('/settings/limits')
  const inputs = {}
  const rows = Object.entries(LIMIT_TEXT).map(([k, [label, step]]) => {
    inputs[k] = h('input', { type: 'number', step, value: lim[k], disabled: !isAdmin, style: 'width:110px' })
    return h('tr', {}, h('td', { text: label }), h('td', { class: 'num' }, inputs[k]))
  })
  return h('div', { class: 'card' }, h('b', { text: 'Limits' }),
    h('p', { class: 'small mute', text: 'Protect against surprise bills and overload. Checked before every search and audit.' }),
    h('table', {}, rows),
    isAdmin ? h('button', { text: 'Save limits', onclick: async () => {
      const body = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, Number(el.value)]))
      try { await api.put('/settings/limits', body); msg.replaceChildren(banner('ok', 'Saved.')) } catch (err) { msg.replaceChildren(banner('bad', err.message)) }
    } }) : h('p', { class: 'small mute', text: 'Only an admin can change limits.' }),
    msg)
}

/** Admin: where Harvey runs (reached only over SSH; its token never leaves the VPS). */
async function harveySettingsCard() {
  const cfg = await api.get('/settings/harvey')
  const msg = h('div')
  const f = {
    host: h('input', { value: cfg.host, placeholder: 'VPS address, e.g. 72.61.203.194' }),
    user: h('input', { value: cfg.user }),
    key: h('input', { value: cfg.key }),
    folder: h('input', { value: cfg.folder }),
    public_url: h('input', { value: cfg.public_url }),
  }
  const save = h('button', { onclick: async () => {
    save.disabled = true
    msg.replaceChildren(h('span', { class: 'live', text: 'Saving and checking the VPS…' }))
    try {
      const r = await api.put('/settings/harvey', Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value.trim()])))
      msg.replaceChildren(r.status.reachable ? banner('ok', `Connected: Harvey is ${r.status.running ? 'running' : 'stopped'} on ${r.host}, ${r.status.outbox.pending} email(s) waiting for approval.`)
        : banner('bad', `Saved, but Harvey did not answer: ${r.status.error}`))
    } catch (err) { msg.replaceChildren(banner('bad', err.message)) }
    save.disabled = false
  } }, 'Save & test')
  return h('div', { class: 'card' },
    h('div', { class: 'section-title' }, h('h2', { text: 'Harvey (outreach on the VPS)' }), cfg.ready ? h('span', { class: 'tag ok', text: 'set up' }) : h('span', { class: 'tag warn', text: 'not set up' })),
    h('p', { class: 'small mute', text: 'This app talks to Harvey only over SSH with the key on this computer. Harvey keeps running on the VPS; its dashboard token stays there.' }),
    h('div', { class: 'row' },
      h('div', { class: 'grow' }, h('label', {}, 'VPS address', f.host)), h('div', {}, h('label', {}, 'SSH user', f.user)),
      h('div', { class: 'grow' }, h('label', {}, 'SSH key on this computer', f.key))),
    h('div', { class: 'row gap' }, h('div', { class: 'grow' }, h('label', {}, 'Harvey folder on the VPS', f.folder)),
      h('div', { class: 'grow' }, h('label', {}, 'Harvey dashboard (for approvals)', f.public_url))),
    cfg.key_found ? null : h('p', { class: 'small bad gap', text: `SSH key not found at ${cfg.key}` }),
    h('div', { class: 'gap' }, save), msg)
}

/** Admin: disk use, old report versions, database backups. */
async function storageCard() {
  const box = h('div', { class: 'card' })
  const figure = (label, value) => h('div', {}, h('div', { class: 'small mute', text: label }), h('div', { class: 'big', text: value }))
  async function render() {
    const st = await api.get('/settings/storage')
    const cleanup = h('button', { class: 'ghost', disabled: !st.old_report_versions, onclick: async () => {
      if (!confirm(`Delete the files of ${st.old_report_versions} old report version(s)? The newest report of every business stays.`)) return
      cleanup.disabled = true
      const r = await api.post('/reports/cleanup')
      toast(`Removed ${r.reports_removed} old report(s), freed ${r.freed_mb} MB`)
      render()
    } }, 'Remove old report versions')
    const backupNow = h('button', { class: 'ghost', onclick: async () => {
      backupNow.disabled = true
      try { const r = await api.post('/settings/backups'); toast(`Backup saved: ${r.name}`) } catch (err) { toast(err.message, 'bad') }
      render()
    } }, icon('shield', 15), 'Back up now')
    fill(box,
      h('div', { class: 'section-title' }, h('h2', { text: 'Storage & backups' }), st.backup_error ? h('span', { class: 'tag bad', text: 'last backup failed' }) : null),
      h('div', { class: 'grid tight' }, figure('Reports', `${st.reports_mb} MB`), figure('Screenshots', `${st.screenshots_mb} MB`),
        figure('Old report versions', String(st.old_report_versions))),
      h('div', { class: 'row' }, cleanup, st.backups_supported ? backupNow : null),
      h('p', { class: 'small mute gap', text: st.backups_supported
        ? `The database is copied every day to backend/data/backups (newest ${st.backup_keep} kept). New screenshots are saved as JPEG, about 6× smaller.`
        : 'PostgreSQL is backed up on the server.' }),
      st.backup_error ? banner('bad', st.backup_error) : null,
      st.backups.length ? h('table', {}, h('tr', {}, h('th', { text: 'Backup' }), h('th', { text: 'Made' }), h('th', { class: 'num', text: 'Size' })),
        st.backups.map((x) => h('tr', {}, h('td', { class: 'mono', text: x.name }), h('td', { class: 'small mute', text: when(x.at) }),
          h('td', { class: 'num', text: `${x.size_mb} MB` })))) : null)
  }
  await render()
  return box
}

/** @param {HTMLElement} root */
// [key, label, admin only]
const SETTING_TABS = [['apify', 'Apify', false], ['limits', 'Limits', false],
  ['ai', 'AI & reports', false], ['harvey', 'Harvey', true], ['storage', 'Storage & backups', true]]

export async function settings(root, user, tab = 'apify') {
  const isAdmin = user?.role === 'admin'
  const tabs = SETTING_TABS.filter(([, , adminOnly]) => isAdmin || !adminOnly)
  const active = tabs.some(([k]) => k === tab) ? tab : 'apify'
  const msg = h('div')
  const cards = h('div', { class: 'grid' })
  const total = h('span', { class: 'tag' })
  const input = h('input', { type: 'password', autocomplete: 'off', placeholder: 'apify_api_...', class: 'grow' })

  function render(data) {
    total.textContent = `${data.accounts.length} account${data.accounts.length === 1 ? '' : 's'} · ${money(data.credit_left_usd)} left`
    cards.replaceChildren(...data.accounts.map((a) => {
      const pct = a.limit_usd ? Math.min(100, Math.round((a.used_usd * 100) / a.limit_usd)) : 0
      return h('div', { class: 'card inner' },
        h('div', { class: 'row-between' }, h('b', { text: a.username || 'Account' }), h('span', { class: 'tag mono', text: a.key })),
        h('div', { class: a.ok && a.remaining_usd > 0.05 ? 'ok' : 'bad', text: a.message }),
        a.ok ? h('div', {},
          h('div', { class: 'big', text: money(a.remaining_usd) }, h('span', { class: 'mute small', text: ` left of ${money(a.limit_usd)}` })),
          h('div', { class: 'bar' }, h('i', { style: `width:${100 - pct}%` })),
          h('div', { class: 'mute small', text: `used ${money(a.used_usd)} · plan ${a.plan || '?'} · resets ${a.cycle_ends || '?'}` })) : null,
        h('div', { class: 'row gap' }, h('button', { class: 'danger', text: 'Remove', onclick: async () => {
          if (!confirm('Remove this Apify token from this computer?')) return
          await api.del(`/apify/accounts/${encodeURIComponent(a.last4)}`)
          render(await api.get('/apify/accounts'))
        } })))
    }))
    if (!data.accounts.length) cards.replaceChildren(banner('bad', 'No Apify account yet — nothing can be collected. Paste a token above.'))
  }

  const apifyCard = () => h('div', { class: 'card' },
      h('div', { class: 'row-between' }, h('b', { text: 'Apify accounts' }), total),
      h('p', { class: 'mute', text: 'Searches use the account with the most credit and switch to the next one by themselves when one runs out. Balances are real, read from Apify.' }),
      isAdmin ? null : h('p', { class: 'small mute', text: 'Only an admin can add or remove Apify accounts.' }),
      !isAdmin ? null : h('form', { class: 'row', onsubmit: async (e) => {
        e.preventDefault()
        const token = input.value.trim()
        if (!token) return
        msg.replaceChildren(h('p', { class: 'mute', text: 'Testing…' }))
        try {
          const st = await api.post('/apify/accounts', { token })
          msg.replaceChildren(banner('ok', `Added ${st.username || st.key}: ${money(st.remaining_usd)} left.`))
        } catch (err) {
          msg.replaceChildren(banner('bad', `Not added: ${err.message}`))
        } finally {
          input.value = ''
          render(await api.get('/apify/accounts'))
        }
      } },
        h('div', { class: 'grow' }, h('label', { text: 'Paste Apify API token (Apify console → Settings → API & Integrations)' }), input),
        h('button', { type: 'submit', text: 'Add & test' }),
        h('button', { type: 'button', class: 'ghost', text: 'Test all', onclick: async () => {
          msg.replaceChildren(h('p', { class: 'mute', text: 'Checking every account…' }))
          render(await api.get('/apify/accounts?fresh=true'))
          msg.replaceChildren()
        } })),
      msg, cards)

  const SECTIONS = {
    apify: async () => [apifyCard()],
    limits: async () => [await limitsCard(isAdmin)],
    ai: async () => [await aiCard(isAdmin), await reportSettingsCard(isAdmin)],
    harvey: async () => [await harveySettingsCard()],
    storage: async () => [await storageCard()],
  }
  fill(root, reveal(h('div', {},
    pageHead('Settings', 'Keys are saved only in backend/.env on this computer and never shown in full again.'),
    h('nav', { class: 'tabs', 'aria-label': 'Settings sections' }, tabs.map(([k, label]) =>
      h('a', { class: `tab ${k === active ? 'on' : ''}`, href: `#/settings/${k}`, 'aria-current': k === active ? 'page' : null, text: label }))),
    ...(await SECTIONS[active]()))))
  if (active === 'apify') render(await api.get('/apify/accounts'))
}
