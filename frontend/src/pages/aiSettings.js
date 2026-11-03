import { api } from '../api.js'
import { badge, banner, chip, fill, h } from '../ui.js'

/** Settings → AI provider (admin can change) and Report settings. */
export async function aiCard(isAdmin) {
  const el = h('div', { class: 'card' })
  const msg = h('div')

  async function render() {
    const st = await api.get('/ai/status')
    const provider = h('select', {}, [['gemini', 'Google Gemini (free tier)'], ['groq', 'Groq (free tier)']].map(([v, t]) => {
      const o = h('option', { value: v, text: t }); o.selected = st.provider === v; return o
    }))
    const key = h('input', { type: 'password', autocomplete: 'off', placeholder: 'Paste the API key here (not in chat)', class: 'grow' })
    const models = h('select', { disabled: true }, h('option', { text: st.model || '—' }))
    if (isAdmin && st.ready) {
      api.get('/ai/models').then((m) => {
        models.replaceChildren(...m.models.map((x) => { const o = h('option', { value: x, text: x }); o.selected = x === m.current; return o }))
        models.disabled = false
      }).catch((err) => msg.replaceChildren(banner('warn', `Could not list models: ${err.message}`)))
    }
    models.onchange = async () => {
      try { await api.put('/ai/model', { model: models.value }); msg.replaceChildren(banner('ok', `Model set to ${models.value}.`)) } catch (err) { msg.replaceChildren(banner('bad', err.message)) }
    }
    fill(el,
      h('div', { class: 'row-between' }, h('b', { text: 'AI provider (reports 7.5 + Main Agent 8.5)' }),
        st.ready ? badge(`${st.provider} · ${st.key} · ${st.model}`, 'ok') : badge('not set up — template wording is used', 'warn')),
      h('p', { class: 'small mute', text: `Used only to word report summaries, translate to Roman Urdu and write the sales call opener — always from checked facts; any answer with a number not in the facts is thrown away. Calls today: ${st.calls_today} of ${st.calls_per_day_max}.` }),
      isAdmin ? h('form', { class: 'row', onsubmit: async (e) => {
        e.preventDefault()
        if (!key.value.trim()) return
        msg.replaceChildren(h('p', { class: 'mute', text: 'Checking the key…' }))
        try {
          const r = await api.post('/ai/key', { provider: provider.value, key: key.value.trim() })
          msg.replaceChildren(banner('ok', `Saved ${r.provider} ${r.key}. ${r.models.length} models available; using ${r.model}.`))
        } catch (err) { msg.replaceChildren(banner('bad', err.message)) }
        key.value = ''
        render()
      } }, h('div', {}, h('label', { text: 'Provider' }), provider), h('div', { class: 'grow' }, h('label', { text: 'API key' }), key),
        h('button', { type: 'submit', text: 'Save & check' })) : h('p', { class: 'small mute', text: 'Only an admin can set the AI key.' }),
      st.ready ? backupBlock(st, isAdmin, msg, render) : null,
      isAdmin && st.ready ? h('div', { class: 'row gap' }, h('div', {}, h('label', { text: 'Model' }), models),
        h('button', { class: 'ghost', text: 'Test AI (1 call)', onclick: async () => {
          msg.replaceChildren(h('p', { class: 'mute', text: 'Asking the model…' }))
          try { const r = await api.post('/ai/test'); msg.replaceChildren(banner('ok', `It answered: “${r.sample}”`)) } catch (err) { msg.replaceChildren(banner('bad', err.message)) }
        } }),
        h('button', { class: 'danger', text: 'Remove key', onclick: async () => {
          if (!confirm('Remove the AI key from this computer? Reports go back to template wording.')) return
          await api.del('/ai/key'); render()
        } })) : null,
      msg)
  }
  await render()
  return el
}

const NAMES = { gemini: 'Google Gemini', groq: 'Groq' }

/** Backup = the other provider; used only when the main one fails (free-tier limit, outage, retired model). */
function backupBlock(st, isAdmin, msg, render) {
  const other = st.provider === 'gemini' ? 'groq' : 'gemini'
  const b = st.backup
  const last = b && b.last_used ? ` Last used ${b.last_used.at.slice(11, 16)} UTC because: ${b.last_used.reason}` : ''
  const head = h('p', { class: 'small' }, h('b', { text: 'Backup: ' }),
    b ? badge(`${b.provider} · ${b.key}${b.model ? ` · ${b.model}` : ''}`, 'ok') : badge('none', 'warn'),
    h('span', { class: 'mute', text: b ? ` Used automatically if ${st.provider} fails.${last}` : ` Add a ${NAMES[other]} key so reports keep AI wording when ${st.provider} hits its limit.` }))
  if (!isAdmin) return head
  if (b) {
    return h('div', {}, head, h('button', { class: 'ghost', text: 'Remove backup key', onclick: async () => {
      if (!confirm('Remove the backup AI key?')) return
      await api.del('/ai/key?backup=true'); render()
    } }))
  }
  const key = h('input', { type: 'password', autocomplete: 'off', placeholder: `${NAMES[other]} key (backup)`, class: 'grow' })
  return h('div', {}, head, h('form', { class: 'row', onsubmit: async (e) => {
    e.preventDefault()
    if (!key.value.trim()) return
    try {
      const r = await api.post('/ai/key', { provider: other, key: key.value.trim(), as_backup: true })
      msg.replaceChildren(banner('ok', `Backup saved: ${other} ${r.backup ? r.backup.key : ''}.`))
    } catch (err) { msg.replaceChildren(banner('bad', err.message)) }
    key.value = ''
    render()
  } }, h('div', { class: 'grow' }, key), h('button', { type: 'submit', text: 'Save backup' })))
}

export async function reportSettingsCard(isAdmin) {
  const rs = await api.get('/settings/report')
  const msg = h('div')
  const langs = new Set(rs.languages)
  const detail = h('select', { disabled: !isAdmin }, [['summary', 'Summary (top 5 only)'], ['standard', 'Standard'], ['detailed', 'Detailed']]
    .map(([v, t]) => { const o = h('option', { value: v, text: t }); o.selected = rs.detail === v; return o }))
  const aiBox = h('input', { type: 'checkbox', disabled: !isAdmin }); aiBox.checked = rs.ai_wording
  const langChip = (v, t) => { const c = chip(t, v, langs.has(v), (e) => { if (e.target.checked) langs.add(v); else langs.delete(v) }); c.querySelector('input').disabled = !isAdmin; return c }
  return h('div', { class: 'card' }, h('b', { text: 'Report settings' }),
    h('p', { class: 'small mute', text: 'Owner reports are made in each ticked language (Roman Urdu needs the AI provider). The internal sales brief is always English.' }),
    h('div', { class: 'chips' }, langChip('en', 'English'), langChip('roman_urdu', 'Roman Urdu')),
    h('div', { class: 'row gap' }, h('div', {}, h('label', { text: 'Detail' }), detail),
      h('div', {}, h('label', { class: 'chip' }, aiBox, ' Use AI wording when available'))),
    isAdmin ? h('button', { class: 'gap', text: 'Save report settings', onclick: async () => {
      try {
        await api.put('/settings/report', { languages: [...langs], detail: detail.value, ai_wording: aiBox.checked })
        msg.replaceChildren(banner('ok', 'Saved. New reports use these settings.'))
      } catch (err) { msg.replaceChildren(banner('bad', err.message)) }
    } }) : null,
    msg)
}
