// Tiny DOM helpers. Text always goes in via textContent, so data from websites can never inject HTML.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue
    if (k === 'class') el.className = v
    else if (k === 'text') el.textContent = v
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v)
    else if (k === 'dataset') Object.assign(el.dataset, v)
    else el.setAttribute(k, v === true ? '' : v)
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue
    el.append(c instanceof Node ? c : document.createTextNode(String(c)))
  }
  return el
}

export const money = (n) => `$${Number(n || 0).toFixed(2)}`

export function when(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export const badge = (text, kind = '') => h('span', { class: `tag ${kind}`, text })

export function statusBadge(status) {
  const kind = { completed: 'ok', running: 'run', queued: 'run', partial: 'warn', failed: 'bad', pending: '' }[status]
  return badge(status, kind ?? '')
}

export function banner(kind, ...content) {
  return h('div', { class: `banner ${kind}` }, ...content)
}

export function safeLink(url, label) {
  // only http(s) links become clickable
  if (!/^https?:\/\//i.test(url || '')) return h('span', { class: 'mute', text: label || url || '' })
  return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text: label || url })
}

export function chip(label, value, checked, onchange, extraClass = '') {
  const input = h('input', { type: 'checkbox', value, onchange })
  input.checked = !!checked
  return h('label', { class: `chip ${extraClass}` }, input, ' ', label)
}

/** Replace an element's children, skipping null/false (conditional sections). */
export function fill(el, ...kids) {
  el.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false))
}

// ------------------------------------------------------------------ icons (inline SVG, stroke = currentColor)
const ICONS = {
  overview: 'M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3',
  leads: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8',
  results: 'M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9',
  monitor: 'M22 12h-4l-3 9L9 3l-3 9H2',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.8 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.8-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.8H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.8-1.2V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.8 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.8H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1.1z',
  activity: 'M12 8v4l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z',
  phone: 'M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z',
  refresh: 'M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  back: 'M19 12H5M11 18l-6-6 6-6',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  calendar: 'M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  bolt: 'M13 2L3 14h9l-1 8 10-12h-9z',
  menu: 'M3 6h18M3 12h18M3 18h18',
}

export function icon(name, size = 16) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', '0 0 24 24')
  svg.setAttribute('width', size)
  svg.setAttribute('height', size)
  svg.setAttribute('aria-hidden', 'true')
  svg.setAttribute('class', 'ico')
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  p.setAttribute('d', ICONS[name] || '')
  svg.append(p)
  return svg
}

// ------------------------------------------------------------------ motion (all of it is skipped for "reduce motion")
const calm = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Children of `root` fade/slide in one after another (CSS reads --i). */
export function reveal(root, selector = ':scope > *') {
  root.querySelectorAll(selector).forEach((el, i) => {
    el.classList.add('rv')
    el.style.setProperty('--i', Math.min(i, 12))
  })
  return root
}

/** Number that counts up to `value` (keeps prefix/suffix such as "$" or "%"). */
export function countUp(value, { prefix = '', suffix = '', decimals = 0, ms = 900 } = {}) {
  const el = h('span', { class: 'count' })
  const target = Number(value) || 0
  const show = (n) => { el.textContent = `${prefix}${n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}` }
  if (calm() || target === 0) { show(target); return el }
  show(0)
  const start = performance.now()
  const tick = (t) => {
    const k = Math.min(1, (t - start) / ms)
    show(target * (1 - (1 - k) ** 3))
    if (k < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
  return el
}

/** Page title row: title, one-line purpose, actions on the right. */
export function pageHead(title, sub, ...actions) {
  return h('header', { class: 'page-head' },
    h('div', {}, h('h1', { text: title }), sub ? h('p', { class: 'sub', text: sub }) : null),
    actions.length ? h('div', { class: 'actions' }, ...actions) : null)
}

/** Small stat tile with an icon and a counting number. */
export function statTile(label, value, { tone = '', ico = null, prefix = '', suffix = '', decimals = 0, hint = '' } = {}) {
  return h('div', { class: `card stat ${tone}` },
    h('div', { class: 'stat-top' }, h('span', { class: 'l', text: label }), ico ? icon(ico, 15) : null),
    h('div', { class: 'n' }, typeof value === 'number' ? countUp(value, { prefix, suffix, decimals }) : value),
    hint ? h('div', { class: 'hint', text: hint }) : null)
}

/** Horizontal bar list (name, bar, number) that grows in. */
export function barList(rows, empty = 'Nothing yet') {
  if (!rows.length) return h('p', { class: 'mute small', text: empty })
  const max = Math.max(...rows.map(([, n]) => n), 1)
  return h('div', { class: 'barlist' }, rows.map(([label, n], i) => h('div', { class: 'barrow', style: `--i:${i}` },
    h('span', { class: 'bl', text: label }),
    h('span', { class: 'bt' }, h('i', { style: `--w:${(100 * n) / max}%` })),
    h('span', { class: 'bn', text: n.toLocaleString() }))))
}

/** Loading placeholder with the rough shape of a page. */
export function skeleton(rows = 4) {
  return h('div', { class: 'skeleton' }, h('div', { class: 'sk sk-title' }),
    h('div', { class: 'sk-grid' }, [1, 2, 3, 4].map(() => h('div', { class: 'sk sk-tile' }))),
    Array.from({ length: rows }, () => h('div', { class: 'sk sk-line' })))
}

let toastBox = null
/** Short message in the corner that goes away by itself. */
export function toast(text, kind = 'ok') {
  toastBox ??= document.body.appendChild(h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' }))
  const t = h('div', { class: `toast ${kind}`, text })
  toastBox.append(t)
  setTimeout(() => t.classList.add('out'), 3200)
  setTimeout(() => t.remove(), 3700)
}

export const SALES_STATES = [
  ['connected', 'Connected', 'run'], ['not_connected', 'Not connected', ''], ['interested', 'Interested', 'ok'],
  ['follow_up', 'Follow-up', 'warn'], ['not_interested', 'Not interested', 'bad'], ['not_on_whatsapp', 'Not on WhatsApp', ''],
  ['won', 'Won', 'won'], ['called', 'Called', 'run'], ['no_answer', 'No answer', ''],
]

export function salesBadge(sales) {
  if (!sales) return badge('Not called', 'ghost')
  const [, label, kind] = SALES_STATES.find(([k]) => k === sales.status) || [, sales.status, '']
  return badge(sales.status === 'follow_up' && sales.follow_up_on ? `${label} · ${sales.follow_up_on}` : label, kind)
}
