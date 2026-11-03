import { api } from '../api.js'
import { can, ownerName, teamList } from '../access.js'
import { badge, banner, fill, h, icon, safeLink, statusBadge, toast, when } from '../ui.js'
import { agentSection } from './agentSections.js'
import { scoreRing } from './overview.js'
import { pitchTab } from './pitchTab.js'
import { reportViewer } from './reportViewer.js'
import { salesCard } from './salesCard.js'
import { socialSection } from './socialFinder.js'
import { websiteAuditSection } from './websiteAudit.js'

const TABS = [['overview', 'Overview'], ['report', 'Audit report'], ['pitch', 'Sales pitch'], ['calls', 'Calls'],
  ['agents', 'Agents'], ['sources', 'Sources']]
const AGENT_LABEL = { website_expert: 'Website', social_media_finder: 'Social finder', social_media_expert: 'Social media',
  automation_runner: 'Automation', data_organizer: 'Summary', reporting: 'Reports', main: 'Score' }
const RANK = { viewer: 0, sales: 1, admin: 2 }

function profileCard(b) {
  const d = b.details || {}
  const fact = (label, value) => (value ? [h('dt', { text: label }), h('dd', {}, value)] : [])
  return h('section', { class: 'card' }, h('h2', { text: 'Business profile' }), h('dl', { class: 'kv gap' },
    fact('Category', b.category), fact('City · area', [b.city, b.area].filter(Boolean).join(' · ')),
    fact('Phone', b.phone ? `${b.phone}${d.phone_type ? ` (${d.phone_type})` : ''}` : ''),
    fact('Email', b.email), fact('Website', b.website_url ? safeLink(b.website_url) : ''),
    fact('Google Maps', b.maps_url ? safeLink(b.maps_url, 'open listing') : ''),
    fact('Rating', b.rating ? `${b.rating}★ from ${b.review_count ?? 0} reviews` : ''),
    fact('Newest review', d.last_review_date), fact('Opening hours', (d.opening_hours || []).join(' · ')),
    d.temporarily_closed ? fact('Note', 'Temporarily closed on Google Maps') : []))
}

function scoreCard(b) {
  const o = (b.details || {}).opportunity
  if (!o) return h('section', { class: 'card empty' }, icon('results'), h('div', { text: 'Not audited yet. Run a full audit to get a score, a report and a sales pitch.' }))
  return h('section', { class: 'card' },
    h('div', { style: 'display:flex;gap:14px;align-items:center' }, scoreRing(o.score), h('div', {}, h('h2', { text: o.band }), h('div', { class: 'small mute', text: o.label }))),
    h('ul', { class: 'list-plain gap' }, Object.entries(o.breakdown || {}).map(([k, v]) => h('li', {},
      h('span', { class: 'small' }, h('b', { text: `${k[0].toUpperCase()}${k.slice(1)}: ` }), v.why),
      h('span', { class: 'small mute', style: 'white-space:nowrap', text: `${v.points}/${v.out_of}` })))),
    h('div', { class: 'row gap' }, h('a', { class: 'btn', href: `#/leads/${b.id}/pitch` }, 'Sales pitch', icon('arrow', 14)),
      h('a', { class: 'btn ghost', href: `#/leads/${b.id}/report` }, 'Audit report')))
}

function auditRuns(b) {
  return h('section', { class: 'card' }, h('h2', { text: 'Audit runs' }),
    b.audit_jobs.length ? b.audit_jobs.map((j) => h('div', { class: 'job' },
      h('div', {}, h('b', { text: `Audit #${j.id}` }), ' ', statusBadge(j.status), ' ', h('span', { class: 'mute small', text: when(j.created_at) })),
      h('div', { class: 'chips gap' }, j.tasks.map((t) => badge(`${AGENT_LABEL[t.agent_name] || t.agent_name} · ${t.status}`,
        t.status === 'completed' ? 'ok' : t.status === 'failed' ? 'bad' : t.status === 'running' ? 'run' : '')))))
      : h('p', { class: 'mute small', text: 'No audit yet.' }))
}

function sourcesTab(b) {
  return h('section', { class: 'card wrap' }, h('h2', { text: 'Where each detail came from' }),
    h('table', {}, h('tr', {}, ...['Field', 'Source', 'Method', 'Checked?', 'Collected'].map((t) => h('th', { text: t }))),
      b.data_sources.map((s) => h('tr', {},
        h('td', { text: s.field || 'whole record' }),
        h('td', {}, s.source_url ? safeLink(s.source_url, s.source_type) : s.source_type),
        h('td', { class: 'mute', text: s.collection_method }),
        h('td', {}, badge(s.verification_status, s.verification_status === 'verified' ? 'ok' : '')),
        h('td', { class: 'mute small', text: when(s.collected_at) })))))
}

/** One lead, one place: profile, report, pitch, calls, agent detail and sources as tabs (#/leads/{id}/{tab}). */
export async function leadDetail(root, id, user, tab = 'overview') {
  const b = await api.get(`/businesses/${id}`)
  const d = b.details || {}
  const [team, canAssign, canAudit] = await Promise.all([teamList(), can(user, 'assign_leads'), can(user, 'start_audits')])
  const active = TABS.some(([k]) => k === tab) ? tab : 'overview'
  const ownerBox = h('span', { class: 'owner-box' })
  function drawOwner() {
    if (canAssign) {
      const sel = h('select', { class: 'small-select', 'aria-label': 'Lead owner' }, h('option', { value: '', text: 'Owner: nobody' }),
        team.filter((t) => t.is_active || t.id === b.owner_id).map((t) => { const o = h('option', { value: t.id, text: `Owner: ${t.name}` }); o.selected = t.id === b.owner_id; return o }))
      sel.onchange = async () => {
        try {
          await api.post('/leads/assign', { business_ids: [b.id], user_id: sel.value ? Number(sel.value) : null })
          b.owner_id = sel.value ? Number(sel.value) : null
          toast(b.owner_id ? `Given to ${ownerName(team, b.owner_id)}` : 'Lead unassigned')
        } catch (err) { toast(err.message, 'bad'); drawOwner() }
      }
      return fill(ownerBox, sel)
    }
    if (!b.owner_id && RANK[user?.role] >= RANK.sales) {
      return fill(ownerBox, h('button', { class: 'ghost', onclick: async () => {
        try { await api.post(`/businesses/${b.id}/take`); b.owner_id = user.id; toast('This lead is yours now'); drawOwner() } catch (err) { toast(err.message, 'bad') }
      } }, 'Take this lead'))
    }
    return fill(ownerBox, badge(b.owner_id === user?.id ? 'Your lead' : `Owner: ${ownerName(team, b.owner_id) || 'nobody'}`, b.owner_id ? 'run' : 'ghost'))
  }
  drawOwner()
  const body = h('div', { class: 'tab-body' })
  const stops = []

  const fullAudit = h('button', { disabled: !canAudit, onclick: async () => {
    fullAudit.disabled = true
    try {
      await api.post(`/businesses/${b.id}/full-audit`)
      toast('Full audit started — the score, report and pitch update when it finishes')
    } catch (err) { toast(err.message, 'bad'); fullAudit.disabled = false }
  } }, icon('bolt', 15), d.opportunity ? 'Audit again' : 'Run full audit')

  async function show() {
    fill(body, h('div', { class: 'skeleton' }, h('div', { class: 'sk sk-line' }), h('div', { class: 'sk sk-line' })))
    if (active === 'overview') fill(body, h('div', { class: 'grid two' }, scoreCard(b), profileCard(b)))
    else if (active === 'report') fill(body, reportViewer(await api.get(`/reports?business_id=${b.id}&limit=100`)))
    else if (active === 'pitch') fill(body, await pitchTab(b))
    else if (active === 'calls') fill(body, await salesCard(b, user))
    else if (active === 'sources') fill(body, sourcesTab(b))
    else {
      const parts = [agentSection(b, 'main'), agentSection(b, 'reporting'), agentSection(b, 'organizer'), socialSection(b),
        agentSection(b, 'social'), websiteAuditSection(b), agentSection(b, 'automation')]
      parts.forEach((p) => stops.push(p.stop))
      fill(body, h('p', { class: 'small mute', text: 'What each agent found, in detail. Sales usually only needs the Audit report and Sales pitch tabs.' }),
        auditRuns(b), ...parts.map((p) => p.el))
    }
  }

  fill(root,
    h('a', { href: '#/leads', class: 'crumb' }, icon('back', 14), 'All leads'),
    h('header', { class: 'page-head' },
      h('div', { style: 'display:flex;gap:16px;align-items:center;min-width:0' }, d.opportunity ? scoreRing(d.opportunity.score) : null,
        h('div', { style: 'min-width:0' }, h('h1', { text: b.name }),
          h('p', { class: 'sub' }, badge(b.business_id), badge(b.industry || 'industry ?'),
            d.opportunity ? badge(d.opportunity.band, d.opportunity.score >= 60 ? 'ok' : '') : badge('not audited yet', 'ghost'),
            d.harvey ? badge('in Harvey', 'run') : null))),
      h('div', { class: 'actions' }, ownerBox, b.phone ? h('a', { class: 'btn ghost', href: `tel:${b.phone}` }, icon('phone', 15), b.phone) : null,
        canAudit ? fullAudit : null)),
    h('nav', { class: 'tabs', 'aria-label': 'Lead sections' }, TABS.map(([k, label]) =>
      h('a', { class: `tab ${k === active ? 'on' : ''}`, href: `#/leads/${b.id}/${k}`, 'aria-current': k === active ? 'page' : null, text: label }))),
    body)
  await show().catch((err) => fill(body, banner('bad', err.message)))
  return () => stops.forEach((s) => s())
}
