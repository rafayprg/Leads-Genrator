import { api } from '../api.js'
import { banner, fill, h, icon, pageHead, reveal, when } from '../ui.js'

const TYPES = [['owner_summary', 'For the owner'], ['internal_sales', 'Sales brief (internal)']]
const LANGS = [['en', 'English'], ['roman_urdu', 'Roman Urdu']]

function seg(options, value, onPick, available) {
  return h('div', { class: 'seg', role: 'radiogroup' }, options.map(([v, label]) => h('button', {
    type: 'button', role: 'radio', class: v === value ? 'on' : '', 'aria-checked': String(v === value),
    disabled: available && !available.has(v), text: label, onclick: () => onPick(v) })))
}

/**
 * The report exactly as it is printed, shown inside the app (no new tab).
 * The frame may not run scripts; same-origin only so its height and Print work.
 * @param {Array} reports  /reports?business_id= rows  @param {number|null} startId
 */
export function reportViewer(reports, startId = null) {
  const el = h('div', { class: 'report-viewer' })
  if (!reports.length) {
    fill(el, h('div', { class: 'card empty' }, icon('results'), h('div', { text: 'No report yet. Run a full audit — the reports are made at the end.' })))
    return el
  }
  const start = reports.find((r) => r.id === startId) || reports.find((r) => r.report_type === 'owner_summary') || reports[0]
  const pick = { type: start.report_type, language: start.language, id: start.id }

  function current() {
    return reports.find((r) => r.id === pick.id && r.report_type === pick.type && r.language === pick.language)
      || reports.filter((r) => r.report_type === pick.type && r.language === pick.language).sort((a, b) => b.version - a.version)[0]
  }

  function draw() {
    const rep = current()
    const types = new Set(reports.map((r) => r.report_type))
    const langs = new Set(reports.filter((r) => r.report_type === pick.type).map((r) => r.language))
    const versions = reports.filter((r) => r.report_type === pick.type && r.language === pick.language).sort((a, b) => b.version - a.version)
    const frame = h('iframe', { class: 'report-frame', title: 'Audit report', sandbox: 'allow-same-origin allow-modals', src: rep ? `/api/reports/${rep.id}/html` : 'about:blank' })
    frame.onload = () => {
      try { frame.style.height = `${frame.contentDocument.documentElement.scrollHeight + 24}px` } catch { /* keep the default height */ }
      frame.classList.add('ready')
    }
    const version = versions.length > 1 ? h('select', { class: 'small-select', 'aria-label': 'Version', onchange: (e) => { pick.id = Number(e.target.value); draw() } },
      versions.map((v) => { const o = h('option', { value: v.id, text: `v${v.version} · ${when(v.created_at)}` }); o.selected = rep && v.id === rep.id; return o })) : null
    fill(el,
      h('div', { class: 'viewer-bar' },
        seg(TYPES, pick.type, (v) => { pick.type = v; pick.id = null; if (!reports.some((r) => r.report_type === v && r.language === pick.language)) pick.language = 'en'; draw() }, types),
        seg(LANGS, pick.language, (v) => { pick.language = v; pick.id = null; draw() }, langs),
        version,
        h('span', { class: 'grow-space' }),
        rep ? h('button', { type: 'button', class: 'ghost small', onclick: () => frame.contentWindow?.print() }, 'Print') : null,
        rep?.has_pdf ? h('a', { class: 'btn ghost small', href: `/api/reports/${rep.id}/pdf`, download: '' }, icon('download', 14), 'PDF') : null),
      rep ? frame : banner('warn', 'This report is not made in this language. Turn Roman Urdu on in Settings → Report settings and run the audit again.'))
  }
  draw()
  return el
}

/** #/reports/{id}: one report full width, with a way back to its lead. */
export async function reportPage(root, id) {
  const meta = await api.get(`/reports/${id}`)
  const [reports, lead] = await Promise.all([api.get(`/reports?business_id=${meta.business_id}&limit=100`), api.get(`/businesses/${meta.business_id}`)])
  fill(root, reveal(h('div', {},
    h('a', { href: `#/leads/${lead.id}/report`, class: 'crumb' }, icon('back', 14), lead.name),
    pageHead('Audit report', `${lead.name} · ${lead.business_id}`,
      h('a', { class: 'btn ghost', href: `#/leads/${lead.id}/pitch` }, 'Sales pitch', icon('arrow', 14))),
    reportViewer(reports, Number(id)))))
}
