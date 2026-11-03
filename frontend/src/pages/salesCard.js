import { api } from '../api.js'
import { SALES_STATES, fill, h, icon, salesBadge, toast, when } from '../ui.js'

const RANK = { viewer: 0, sales: 1, admin: 2 }
const LABEL = Object.fromEntries(SALES_STATES.map(([k, l]) => [k, l]))

/** Call tracking on the lead page: pick an outcome, add a note / follow-up date, see every earlier call. */
export async function salesCard(b, user) {
  const canEdit = RANK[user?.role] >= RANK.sales
  const el = h('section', { class: 'card' })
  let picked = null

  async function render() {
    const hist = await api.get(`/businesses/${b.id}/sales`)
    const note = h('textarea', { rows: 2, placeholder: 'What happened on the call? (optional)', style: 'width:100%;resize:vertical' })
    const date = h('input', { type: 'date', value: new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10) })
    const dateBox = h('div', { hidden: true }, h('label', {}, 'Follow up on', date))
    const save = h('button', { disabled: true }, icon('phone', 15), 'Save call')
    const pick = h('div', { class: 'status-pick', role: 'group', 'aria-label': 'Call outcome' }, SALES_STATES.map(([k, label]) =>
      h('button', { type: 'button', 'aria-pressed': 'false', onclick: (e) => {
        picked = k
        pick.querySelectorAll('button').forEach((x) => { x.classList.toggle('on', x === e.currentTarget); x.setAttribute('aria-pressed', String(x === e.currentTarget)) })
        dateBox.hidden = k !== 'follow_up'
        save.disabled = false
      } }, label)))
    save.onclick = async () => {
      save.disabled = true
      try {
        await api.post(`/businesses/${b.id}/sales`, { status: picked, note: note.value, follow_up_on: picked === 'follow_up' ? date.value : null })
        toast(`Saved: ${LABEL[picked]}`)
        picked = null
        render()
      } catch (err) { toast(err.message, 'bad'); save.disabled = false }
    }
    fill(el,
      h('div', { class: 'section-title' }, h('h2', { text: 'Calls & follow-up' }), salesBadge(hist[0])),
      canEdit ? h('div', {}, pick, h('div', { class: 'row gap' }, h('div', { class: 'grow' }, note), dateBox, save)) : null,
      hist.length ? h('ol', { class: 'timeline' }, hist.slice(0, 12).map((n) => h('li', {},
        h('div', {}, h('b', { text: LABEL[n.status] || n.status }), n.follow_up_on ? h('span', { class: 'small warn', text: ` · follow up ${n.follow_up_on}` }) : null,
          h('span', { class: 'small mute', text: ` · ${when(n.at)} · ${n.by}` })),
        n.note ? h('div', { class: 'small', text: n.note }) : null)))
        : h('p', { class: 'small mute gap', text: 'No calls recorded yet.' }))
  }
  await render()
  return el
}
