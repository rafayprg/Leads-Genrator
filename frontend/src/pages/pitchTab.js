import { api } from '../api.js'
import { badge, fill, h, icon, toast } from '../ui.js'
import { scoreRing } from './overview.js'

async function copy(text, what) {
  try { await navigator.clipboard.writeText(text); toast(`${what} copied`) } catch { toast('Could not copy — select the text instead', 'bad') }
}

const copyBtn = (text, what) => h('button', { type: 'button', class: 'ghost small', onclick: () => copy(text, what) }, 'Copy')

/** Sales pitch for one lead: what to say, from the checked audit facts only. */
export async function pitchTab(b) {
  const p = await api.get(`/businesses/${b.id}/pitch`)
  const el = h('div', { class: 'pitch' })
  if (!p.ready) {
    fill(el, h('div', { class: 'card empty' }, icon('phone'), h('div', { text: p.reason })))
    return el
  }
  const wa = h('textarea', { rows: 3, 'aria-label': 'WhatsApp message', style: 'width:100%;resize:vertical' })
  wa.value = p.whatsapp_text
  const waOpen = () => {
    const digits = (p.phone || '').replace(/\D/g, '')
    window.open(`https://wa.me/${digits}?text=${encodeURIComponent(wa.value)}`, '_blank', 'noopener')
  }

  fill(el,
    h('div', { class: 'grid two' },
      h('section', { class: 'card opener' },
        h('div', { class: 'section-title' }, h('h2', { text: 'Open the call with' }), badge(p.opener_by === 'ai' ? 'AI, from checked facts' : 'template', p.opener_by === 'ai' ? 'ok' : '')),
        h('p', { class: 'say', text: p.opener_roman_urdu }), h('div', { class: 'row-between' }, h('span', { class: 'small mute', text: 'Roman Urdu' }), copyBtn(p.opener_roman_urdu, 'Opener')),
        h('p', { class: 'say en', text: p.opener_en }), h('div', { class: 'row-between' }, h('span', { class: 'small mute', text: 'English' }), copyBtn(p.opener_en, 'English opener')),
        p.synthesis ? h('p', { class: 'small mute gap', text: p.synthesis }) : null,
        p.phone ? h('a', { class: 'btn gap', href: `tel:${p.phone}` }, icon('phone', 15), `Call ${p.phone}`) : null),
      h('section', { class: 'card' },
        h('div', { style: 'display:flex;gap:14px;align-items:center;margin-bottom:10px' }, scoreRing(p.score),
          h('div', {}, h('h2', { text: 'Why call them' }), h('div', { class: 'small mute', text: p.band || '' }))),
        h('ul', { class: 'list-plain' }, p.why_call.map((w) => h('li', {}, h('span', { class: 'small', text: w.why }),
          h('span', { class: 'small mute', style: 'white-space:nowrap', text: `${w.points}/${w.out_of}` })))),
        h('p', { class: 'small mute', text: p.label || '' }))),
    h('section', { class: 'card' }, h('h2', { text: 'Three things to bring up' }),
      p.first_topic ? h('p', { class: 'small mute', text: `Start with: ${p.first_topic}` }) : null,
      h('div', { class: 'points' }, p.talking_points.map((t, i) => h('div', { class: 'point', style: `--i:${i}` },
        h('div', { class: 'row-between' }, h('span', {}, badge(t.priority, t.priority === 'High' ? 'bad' : t.priority === 'Medium' ? 'warn' : ''),
          badge(t.confirmed ? 'seen directly' : 'confirm on the call', t.confirmed ? 'ok' : 'warn')), copyBtn(t.say, 'Line')),
        h('p', { class: 'say', text: t.say }),
        h('p', { class: 'small mute', text: `If they ask how to fix it: ${t.fix}` })))) ),
    h('div', { class: 'grid two' },
      h('section', { class: 'card' }, h('h2', { text: 'What TechDeva can offer' }),
        p.modules.length ? h('ul', { class: 'list-plain' }, p.modules.map((m) => h('li', {},
          h('span', {}, h('b', { text: m.module }), h('div', { class: 'small mute', text: m.because })), badge(m.offer, 'run'))))
          : h('p', { class: 'small mute', text: 'No module clearly fits from the outside — lead with the website problems.' }),
        p.competitor_tools.length ? h('p', { class: 'small gap' }, 'Already uses: ', p.competitor_tools.map((t) => badge(t, 'warn'))) : null,
        p.note ? h('p', { class: 'small mute', text: p.note }) : null),
      h('section', { class: 'card' }, h('div', { class: 'section-title' }, h('h2', { text: 'WhatsApp message' }), copyBtn(p.whatsapp_text, 'Message')),
        wa, h('div', { class: 'row gap' },
          h('button', { type: 'button', class: 'ghost', onclick: () => copy(wa.value, 'Message') }, 'Copy my version'),
          p.whatsapp_link ? h('button', { type: 'button', onclick: waOpen }, 'Open in WhatsApp', icon('arrow', 14))
            : h('span', { class: 'small mute', text: 'No mobile number on record, so no WhatsApp link.' })))),
    h('div', { class: 'grid two' },
      h('section', { class: 'card' }, h('h2', { text: 'If they say…' }),
        p.objections.map((o) => h('details', { class: 'objection' }, h('summary', { text: `“${o.they_say}”` }), h('p', { class: 'say', text: o.answer })))),
      h('section', { class: 'card' }, h('h2', { text: 'Ask to confirm' }),
        p.to_confirm.length ? h('ul', { class: 'checks' }, p.to_confirm.map((x) => h('li', {}, h('label', { class: 'pick-item' }, h('input', { type: 'checkbox' }), x))))
          : h('p', { class: 'small mute', text: 'Everything in the report was seen directly.' }),
        h('p', { class: 'small mute', text: 'These were inferred from outside. Ask, do not claim.' }))))
  return el
}
