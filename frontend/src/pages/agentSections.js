import { api } from '../api.js'
import { badge, banner, fill, h, statusBadge, when } from '../ui.js'
import { finding } from './websiteAudit.js'

const POLL_MS = 3000

function toolsTable(tools) {
  if (!tools?.length) return h('p', { class: 'mute', text: 'No booking, chat, CRM or tracking tools seen on the website.' })
  return h('table', {}, h('tr', {}, ...['Tool', 'Type', 'Seen on'].map((t) => h('th', { text: t }))),
    tools.map((t) => h('tr', {}, h('td', {}, h('b', { text: t.name }), t.competitor ? [' ', badge('competitor', 'warn')] : null),
      h('td', { class: 'mute', text: t.kind.replace('_', ' ') }), h('td', { class: 'mute small', text: t.seen_on.join(', ') }))))
}

function opportunities(list) {
  if (!list?.length) return null
  return h('table', {}, h('tr', {}, ...['Manual step / gap', 'Suggested automation', 'TechDeva'].map((t) => h('th', { text: t }))),
    list.map((o) => h('tr', {},
      h('td', { text: o.business_problem }),
      h('td', { text: o.recommended_solution }),
      h('td', {}, o.techdeva_capability.name, h('br'),
        badge(o.techdeva_capability.offer, o.techdeva_capability.status === 'existing' ? 'ok' : 'warn')))))
}

const STATUS_KIND = { complete: 'ok', partial: 'warn', limited: 'warn', failed: 'bad', not_run: '', skipped: '' }
const QUALITY = {
  verified: ['seen directly', 'ok'], requires_verification: ['confirm first', 'warn'],
  requires_review: ['check by hand', 'warn'], missing_evidence: ['no evidence', 'bad'], stale: ['old — re-run', 'bad'],
}
const AGENT_SHORT = { website_expert: 'Agent 1', social_media_finder: 'Agent 3', social_media_expert: 'Agent 2', automation_runner: 'Agent 4' }

function organizerBody(s) {
  return [
    h('p', {}, h('b', { text: s.overall_completeness }), ` · ${s.issues.length} issue(s) after merging · ${s.needs_verification} to confirm`),
    h('table', {}, s.completeness.map((r) => h('tr', {}, h('td', { text: r.section }),
      h('td', {}, badge(r.status.replace('_', ' '), STATUS_KIND[r.status] ?? '')), h('td', { class: 'small mute', text: r.reason })))),
    s.contradictions.length ? h('div', {}, h('b', { class: 'small', text: 'Agents disagree' }),
      s.contradictions.map((c) => banner('warn', c.statement))) : null,
    s.next_steps.length ? h('div', {}, h('b', { class: 'small', text: 'Next steps' }),
      h('ol', { class: 'small' }, s.next_steps.map((x) => h('li', { text: x })))) : null,
    s.issues.length ? h('div', {}, h('b', { class: 'small', text: 'All issues, merged across agents' }),
      h('table', {}, s.issues.map((i) => h('tr', {},
        h('td', {}, badge(i.severity, { critical: 'bad', high: 'bad', medium: 'warn' }[i.severity] || '')),
        h('td', {}, i.issue, i.related.length ? h('div', { class: 'small mute', text: `also: ${i.related.map((r) => r.issue).join(' · ')}` }) : null),
        h('td', { class: 'small' }, i.agents.map((a) => badge(AGENT_SHORT[a] || a))),
        h('td', {}, badge(...(QUALITY[i.status] || [i.status, ''])))))))
      : null,
  ]
}

const REPORT_NAME = { owner_summary: 'For the business owner', internal_sales: 'Internal sales brief' }

function reportBody(s) {
  return [
    h('table', {}, (s.reports || []).map((r) => h('tr', {},
      h('td', {}, h('b', { text: REPORT_NAME[r.report_type] || r.report_type }), ` · v${r.version} `,
        badge(r.language === 'roman_urdu' ? 'Roman Urdu' : 'English'), ' ', badge(r.wording === 'ai' ? 'AI wording' : 'template', r.wording === 'ai' ? 'ok' : '')),
      h('td', { class: 'small mute', text: `${r.recommendations} recommendation(s)` }),
      h('td', {}, h('a', { class: 'btn ghost', href: `#/reports/${r.report_id}`, text: 'Open' }), ' ',
        r.pdf ? h('a', { class: 'btn ghost', href: `/api/reports/${r.report_id}/pdf`, text: 'PDF' }) : h('span', { class: 'small mute', text: 'no PDF' }))))),
    h('p', { class: 'small mute', text: 'The owner version leaves out our own doubts and all sales notes. Languages, detail and AI wording: Settings → Report settings.' }),
  ]
}

const BAND_KIND = { 'High priority': 'ok', 'Medium-high': 'ok', 'Qualify further': 'warn', 'Lower priority': '' }

function mainBody(s) {
  const o = s.opportunity
  return [
    h('div', { class: 'row-between' },
      h('div', {}, h('span', { class: 'big', text: `${o.score}/100` }), ' ', badge(o.band, BAND_KIND[o.band] || '')),
      badge(s.overall_audit_status, s.overall_audit_status === 'completed' ? 'ok' : 'warn')),
    h('p', { class: 'small mute', text: o.label }),
    h('table', {}, Object.entries(o.breakdown).map(([k, v]) => h('tr', {},
      h('td', { text: k }), h('td', { class: 'num', text: `${v.points}/${v.out_of}` }), h('td', { class: 'small mute', text: v.why })))),
    o.ai_note ? h('div', { class: 'banner ok' }, h('b', { text: 'Before the call (AI, from checked facts): ' }), o.ai_note.synthesis,
      h('div', { class: 'gap' }, h('b', { text: 'Opener: ' }), o.ai_note.opener_roman_urdu), h('div', { class: 'small' }, o.ai_note.opener_en)) : null,
    h('p', { class: 'small' }, ...Object.entries(s.statuses).map(([k, v]) => badge(`${k.replace('_', ' ')}: ${v}`,
      v === 'completed' ? 'ok' : v === 'failed' ? 'bad' : ''))),
  ]
}

const AGENTS = {
  main: {
    title: 'Main Agent — audit record & opportunity score',
    run: 'Recalculate score',
    note: 'Last step of a full audit. Score = website 25 + social 25 + automation 30 + details 10 + contact 10. Use "Run full audit" above to run every agent in order.',
    ownFindings: false,
    body: mainBody,
  },
  reporting: {
    title: 'Report (Agent 6)',
    run: 'Make report',
    note: 'Builds two reports from the audit summary: one for the business owner, one internal for sales. Runs Agent 5 first.',
    ownFindings: false,
    body: reportBody,
  },
  organizer: {
    title: 'Audit summary (Agent 5 — data organizer)',
    run: 'Build summary',
    note: 'Combines the latest results of Agents 1–4: merges the same issue, checks evidence, flags disagreements. Adds no new claims.',
    ownFindings: false,
    body: organizerBody,
  },
  social: {
    title: 'Social media (Agent 2 — presence only)',
    run: 'Check social presence',
    note: 'No posts or engagement are read (no scraping). Judges only the accounts Agent 3 found. Run Agent 3 first.',
    body: (s) => [
      s.platforms_analyzed?.length
        ? h('p', {}, 'Official accounts: ', ...s.platforms_analyzed.map((p) => badge(`${p.platform} (${p.confidence})`)))
        : null,
    ],
  },
  automation: {
    title: 'Automation (Agent 4 — audit only)',
    run: 'Check automation',
    note: 'Reads the public website only. Runs no workflow and touches no business system.',
    body: (s) => [
      h('b', { class: 'small', text: 'Tools already in use' }), toolsTable(s.existing_automation),
      s.opportunities?.length ? h('b', { class: 'small', text: 'Where TechDeva could help' }) : null,
      opportunities(s.opportunities),
    ],
  },
}

/** Generic block for Agents 2 and 4. Returns { el, stop }. */
export function agentSection(b, key) {
  const cfg = AGENTS[key]
  const el = h('div', { class: 'card' })
  let timer = null

  async function start(btn) {
    btn.disabled = true
    try { await api.post(`/businesses/${b.id}/agents/${key}`) } catch (err) { el.prepend(banner('bad', err.message)) }
    load()
  }

  async function load() {
    clearTimeout(timer)
    const a = await api.get(`/businesses/${b.id}/agents/${key}`)
    const running = a.task_status === 'pending' || a.task_status === 'running'
    const s = a.summary
    fill(el,
      h('div', { class: 'row-between' }, h('b', { text: cfg.title }),
        h('span', {}, a.task_status ? statusBadge(a.task_status) : null, ' ',
          h('button', { text: s ? 'Run again' : cfg.run, disabled: running, onclick: (e) => start(e.target) }))),
      h('p', { class: 'small mute', text: cfg.note }),
      running ? h('p', { class: 'mute', text: 'Working…' }) : null,
      a.error ? banner('warn', `Last attempt had a problem: ${a.error}`) : null,
      s?.evaluation_status === 'failed' ? banner('bad', `${s.limitations?.[0] || 'Website could not be read'}. Run again later.`) : null,
      s ? cfg.body(s) : null,
      s && a.findings.length ? h('div', { class: 'findings' }, a.findings.map(finding)) : null,
      s && cfg.ownFindings !== false && !a.findings.length && s.evaluation_status !== 'failed' ? h('p', { class: 'ok', text: 'Nothing to flag.' }) : null,
      s && cfg.ownFindings !== false ? h('p', { class: 'small mute', text: `Limits: ${(s.limitations || s.overall_limitations || []).join(' · ')} ${s.completed_at ? `· ${when(s.completed_at)}` : ''}` }) : null,
      s?.built_at ? h('p', { class: 'small mute', text: `Built ${when(s.built_at)} from ${s.inputs.length} agent result(s).` }) : null,
    )
    if (running) timer = setTimeout(load, POLL_MS)
  }

  load().catch((err) => el.replaceChildren(banner('bad', err.message)))
  return { el, stop: () => clearTimeout(timer) }
}
