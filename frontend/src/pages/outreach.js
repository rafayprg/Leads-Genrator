import { api } from '../api.js'
import { badge, banner, countUp, fill, h, icon, pageHead, reveal, statTile, toast, when } from '../ui.js'
import { scoreRing } from './overview.js'

const RANK = { viewer: 0, sales: 1, admin: 2 }
const BANDS = ['High priority', 'Medium-high', 'Qualify further', 'Lower priority']
const PIPE = [['to_write', 'To write'], ['contacted', 'Contacted'], ['replied', 'Replied'], ['interested', 'Interested'], ['ready_to_meet', 'Ready to meet']]
const MAX_BATCH = 50

function harveyCard(st) {
  if (!st.configured) {
    return h('section', { class: 'card' }, h('h2', { text: 'Harvey is not connected' }),
      h('p', { class: 'mute', text: 'Add the VPS address and SSH key in Settings → Harvey. Harvey keeps running on the VPS; this page only talks to it.' }),
      h('a', { class: 'btn ghost', href: '#/settings' }, 'Open Settings', icon('arrow', 14)))
  }
  if (!st.reachable) return banner('bad', `Could not reach Harvey on ${st.host}: ${st.error}`)
  const pipeTop = Math.max(...PIPE.map(([k]) => st.pipeline[k] || 0), 1)
  return h('div', {},
    h('div', { class: 'grid' },
      statTile('Harvey', st.running ? h('span', { class: 'live', style: 'font-size:22px', text: 'Running' }) : 'Stopped',
        { ico: 'bolt', tone: st.running ? '' : 'rose', hint: st.mode === 'approval' ? 'every email waits for your OK' : 'autopilot: sends by itself' }),
      statTile('Waiting for approval', st.outbox.pending, { ico: 'results', tone: st.outbox.pending ? 'amber' : '' }),
      statTile('Prospects in Harvey', st.prospects, { ico: 'leads', tone: 'cyan' }),
      statTile('Sent', st.outbox.sent, { ico: 'arrow', hint: st.outbox.failed ? `${st.outbox.failed} did not send` : '' })),
    st.paused ? banner('warn', 'Sending is paused in Harvey (kill switch is on).') : null,
    h('div', { class: 'grid two' },
      h('section', { class: 'card' }, h('h2', { text: 'Harvey pipeline' }), h('div', { class: 'gap barlist' }, PIPE.map(([k, label], i) =>
        h('div', { class: 'barrow', style: `--i:${i}` }, h('span', { class: 'bl', text: label }),
          h('span', { class: 'bt' }, h('i', { style: `--w:${(100 * (st.pipeline[k] || 0)) / pipeTop}%` })),
          h('span', { class: 'bn', text: st.pipeline[k] || 0 }))))),
      h('section', { class: 'card' }, h('div', { class: 'section-title' }, h('h2', { text: 'Outbox — waiting for you' }),
        h('a', { class: 'btn small', href: st.public_url, target: '_blank', rel: 'noopener noreferrer' }, 'Approve in Harvey', icon('arrow', 14))),
      st.pending_preview.length ? h('ul', { class: 'list-plain' }, st.pending_preview.map((o) => h('li', {},
        h('span', { style: 'min-width:0' }, h('b', { text: o.subject || '(no subject)' }),
          h('div', { class: 'small mute', text: [o.company, o.contact, o.to].filter(Boolean).join(' · ') })),
        o.email_status ? badge(o.email_status, o.email_status === 'verified' ? 'ok' : 'warn') : null)))
        : h('p', { class: 'small mute', text: 'Nothing waiting. New drafts appear here after Harvey writes them.' }))))
}

/** Outreach: what Harvey (on the VPS) is doing, and sending audited leads to it. */
export async function outreach(root, user) {
  const canSend = RANK[user.role] >= RANK.sales
  const head = h('div')
  const list = h('div')
  const result = h('div')
  const picked = new Set()
  const band = h('select', {}, h('option', { value: '', text: 'All bands' }), BANDS.map((b) => h('option', { value: b, text: b })))
  const minScore = h('input', { type: 'number', min: 0, max: 100, value: 40, style: 'width:90px' })
  let items = []

  async function loadStatus(fresh = false) {
    fill(head, h('div', { class: 'skeleton' }, h('div', { class: 'sk-grid' }, [1, 2, 3, 4].map(() => h('div', { class: 'sk sk-tile' })))))
    const st = await api.get(`/harvey/status${fresh ? '?fresh=true' : ''}`)
    fill(head, harveyCard(st), st.reachable ? h('p', { class: 'small mute', text: `Read from ${st.host} ${when(new Date(st.fetched_at * 1000).toISOString())}` }) : null)
  }

  const autoBox = h('div')
  async function loadAuto() {
    if (user.role !== 'admin') return
    const a = await api.get('/harvey/auto')
    const box = h('input', { type: 'checkbox', role: 'switch', onchange: async (e) => {
      try {
        await api.put('/harvey/auto', { enabled: e.target.checked })
        toast(e.target.checked ? 'Auto-send on' : 'Auto-send off')
      } catch (err) {
        toast(err.message, 'bad')
      }
      loadAuto()
    } })
    box.checked = a.enabled
    fill(autoBox, h('section', { class: 'card' },
      h('label', { class: 'switch' }, box, h('span', { class: 'track' }),
        h('span', {}, h('b', { text: 'Auto-send every new lead to Harvey' }),
          h('span', { class: 'small mute', text: ` — checked every 10 minutes, up to ${MAX_BATCH} at a time` }))),
      a.last_run ? h('p', { class: 'small mute', text: `Last auto-send ${when(a.last_run)}: ${a.last_result}` }) : null))
  }

  const sendBtn = h('button', { disabled: true }, icon('arrow', 15), 'Send to Harvey')
  const checkBtn = h('button', { class: 'ghost', disabled: true }, 'Check with Harvey first')

  function updateButtons() {
    const n = picked.size
    checkBtn.disabled = !n || !canSend
    sendBtn.disabled = !n || !canSend || n > MAX_BATCH
    sendBtn.lastChild.textContent = n ? `Send ${n} to Harvey` : 'Send to Harvey'
  }

  async function run(checkOnly) {
    const ids = [...picked]
    if (!checkOnly && !confirm(`Add ${ids.length} lead(s) to Harvey on the VPS? Harvey will research them and draft emails; nothing is sent until you approve it in Harvey.`)) return
    checkBtn.disabled = sendBtn.disabled = true
    fill(result, h('div', { class: 'card' }, h('span', { class: 'live', text: checkOnly ? 'Harvey is reading the batch…' : 'Adding to Harvey…' })))
    try {
      const r = await api.post('/harvey/send', { business_ids: ids, check_only: checkOnly })
      const facts = checkOnly
        ? `${r.rows ?? r.leads} businesses · ${r.with_website ?? '?'} with a website · ${r.with_owner_email ?? '?'} with an owner email`
        : `${r.new ?? '?'} new in Harvey · ${r.already_known ?? 0} Harvey already knew`
      fill(result, h('div', { class: 'card' }, h('div', { class: 'section-title' }, h('h2', { text: checkOnly ? 'Harvey checked the batch (nothing saved)' : 'Sent to Harvey' }),
        badge(checkOnly ? 'check only' : 'done', checkOnly ? 'run' : 'ok')),
      h('p', { text: facts }), r.skipped ? h('p', { class: 'small mute', text: `${r.skipped} lead(s) skipped (already sent or no website/email).` }) : null,
      h('details', {}, h('summary', { class: 'small mute', text: "Harvey's own words" }), h('pre', { class: 'log', text: r.output.join('\n') }))))
      if (checkOnly) toast('Harvey checked the batch'); else { toast(`Sent ${r.leads} lead(s) to Harvey`); picked.clear(); loadList(); loadStatus(true) }
    } catch (err) {
      fill(result, banner('bad', err.message))
    }
    updateButtons()
  }
  checkBtn.onclick = () => run(true)
  sendBtn.onclick = () => run(false)

  async function loadList() {
    const p = new URLSearchParams({ min_score: String(Number(minScore.value) || 0) })
    if (band.value) p.set('band', band.value)
    const data = await api.get(`/harvey/candidates?${p}`)
    items = data.items
    for (const id of [...picked]) if (!items.some((x) => x.id === id)) picked.delete(id)
    const all = h('input', { type: 'checkbox', 'aria-label': 'Pick the first 50' })
    all.onchange = () => {
      picked.clear()
      if (all.checked) items.slice(0, MAX_BATCH).forEach((x) => picked.add(x.id))
      list.querySelectorAll('tbody input, table tr input.pick').forEach((box) => { box.checked = picked.has(Number(box.value)) })
      updateButtons()
    }
    fill(list, h('div', { class: 'row-between' },
      h('span', { class: 'small mute', text: `${data.total} audited lead(s) ready for Harvey · ${data.already_sent} already sent` }),
      h('span', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, checkBtn, sendBtn)),
    items.length ? h('table', { class: 'rows-in hover' },
      h('tr', {}, h('th', {}, canSend ? all : null), ...['Score', 'Business', 'Website', 'Email'].map((t) => h('th', { text: t }))),
      items.map((x, i) => {
        const box = h('input', { type: 'checkbox', class: 'pick', value: x.id, disabled: !canSend, 'aria-label': `Pick ${x.name}` })
        box.checked = picked.has(x.id)
        box.onchange = () => { if (box.checked) picked.add(x.id); else picked.delete(x.id); updateButtons() }
        return h('tr', { style: `--r:${i}` }, h('td', {}, box), h('td', {}, scoreRing(x.score)),
          h('td', {}, h('a', { href: `#/leads/${x.id}`, text: x.name }), h('div', { class: 'small mute', text: [x.business_id, x.industry, x.city].filter(Boolean).join(' · ') })),
          h('td', { class: 'small' }, x.website ? h('span', { text: x.website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '') }) : h('span', { class: 'mute', text: '—' })),
          h('td', { class: 'small' }, x.email ? x.email : h('span', { class: 'mute', text: 'Harvey will look' })))
      }))
      : h('div', { class: 'empty' }, icon('results'), h('div', { text: 'No audited lead is waiting. Audit more leads, or lower the minimum score.' })))
    updateButtons()
  }
  band.onchange = loadList
  minScore.onchange = loadList

  const page = h('div', {},
    pageHead('Outreach', 'Harvey runs on the VPS and writes the cold emails. Send it your best audited leads; every email still waits for your approval in Harvey.',
      h('button', { class: 'ghost', onclick: () => loadStatus(true) }, icon('refresh', 15), 'Refresh')),
    head,
    autoBox,
    h('section', { class: 'card' }, h('h2', { text: 'Send audited leads to Harvey' }),
      h('p', { class: 'small mute', text: `Only audited leads with a website or an email. Up to ${MAX_BATCH} per batch. A lead sent once is not offered again.` }),
      h('div', { class: 'row gap' }, h('div', {}, h('label', {}, 'Band', band)), h('div', {}, h('label', {}, 'Minimum score', minScore))),
      h('div', { class: 'gap' }, list)),
    result)
  reveal(page)
  fill(root, page)
  await Promise.all([loadStatus(), loadList(), loadAuto()])
}
