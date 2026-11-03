import { api } from '../api.js'
import { banner, fill, h, icon } from '../ui.js'

const FLOW = [['search', 'Collect leads from Google Maps'], ['bolt', 'Seven agents audit each business'],
  ['results', 'Score, issues and a ready call opener'], ['phone', 'Track every call until it is won']]

/** Login, or first-time setup of the admin account. Calls onDone(user) when signed in. */
export async function loginPage(root, onDone) {
  const { needs_setup: setup } = await api.get('/auth/status')
  const msg = h('div')
  const name = h('input', { autocomplete: 'name', required: true })
  const email = h('input', { type: 'email', autocomplete: 'username', required: true })
  const password = h('input', { type: 'password', autocomplete: setup ? 'new-password' : 'current-password', required: true })
  const btn = h('button', { type: 'submit', text: setup ? 'Create admin account' : 'Log in' })
  const field = (label, input) => h('div', { class: 'gap' }, h('label', {}, label, input))
  const team = setup ? [] : await api.get('/auth/team').catch(() => [])
  let mode = 'email'

  // Team tab: pick your name, type the PIN your admin gave you (the PIN is never shown here)
  const pinMsg = h('div')
  const member = h('select', { required: true, 'aria-label': 'Your name' }, h('option', { value: '', text: 'Pick your name…' }),
    team.map((t) => h('option', { value: t.id, text: t.name })))
  const pin = h('input', { type: 'password', inputmode: 'numeric', autocomplete: 'off', pattern: '\\d{4,8}', maxlength: 8, required: true, 'aria-label': 'PIN' })
  const pinBtn = h('button', { type: 'submit', text: 'Log in' })
  const pinForm = h('form', { class: 'gap', hidden: true, onsubmit: async (e) => {
    e.preventDefault()
    pinBtn.disabled = true
    pinMsg.replaceChildren()
    try {
      onDone(await api.post('/auth/pin-login', { user_id: Number(member.value), pin: pin.value }))
    } catch (err) {
      pinMsg.replaceChildren(banner('bad', err.message))
      pinBtn.disabled = false
    }
  } }, field('Your name', member), field('PIN', pin), h('div', { class: 'gap' }, pinMsg, pinBtn))
  const tabs = h('div', { class: 'tabs', role: 'tablist' })
  const drawTabs = () => fill(tabs, [['email', 'Admin / email'], ['pin', 'Team (PIN)']].map(([k, label]) =>
    h('button', { type: 'button', role: 'tab', class: `tab ${mode === k ? 'on' : ''}`, 'aria-selected': String(mode === k), text: label, onclick: () => {
      mode = k
      emailForm.hidden = k !== 'email'
      pinForm.hidden = k !== 'pin'
      drawTabs()
    } })))
  const emailForm = h('form', { class: 'gap', onsubmit: async (e) => {
    e.preventDefault()
    btn.disabled = true
    msg.replaceChildren()
    try {
      const user = setup
        ? await api.post('/auth/setup', { name: name.value.trim(), email: email.value.trim(), password: password.value })
        : await api.post('/auth/login', { email: email.value.trim(), password: password.value })
      onDone(user)
    } catch (err) {
      msg.replaceChildren(banner('bad', err.message))
      btn.disabled = false
    }
  } },
  setup ? field('Your name', name) : null,
  field('Email', email),
  field(setup ? 'Password (at least 10 characters, letters and numbers)' : 'Password', password),
  h('div', { class: 'gap' }, msg, btn))

  fill(root, h('div', { class: 'login-wrap' },
    h('section', { class: 'login-art' },
      h('div', { class: 'logo' }, h('span', { class: 'mark' }, icon('bolt', 16)), h('span', {}, 'TechDeva Audit', h('small', { text: 'Gulf & South Asia audits' }))),
      h('div', {}, h('h2', { text: 'From a map pin to a warm sales call.' }),
        h('p', { text: 'Every business is checked from public information only, scored, and handed to sales with what to say first.' })),
      h('div', { class: 'flow' }, FLOW.map(([ico, text], i) => h('div', { style: `--i:${i}` }, icon(ico), text)))),
    h('div', { class: 'login rv' },
      h('h1', { text: setup ? 'Create the admin account' : 'Welcome back' }),
      h('p', { class: 'sub', text: setup
        ? 'First time on this computer. This account can add Apify accounts, spend credit, add users and change limits.'
        : 'Log in to continue.' }),
      !setup && team.length ? tabs : null,
      emailForm,
      pinForm)))
  if (!setup && team.length) drawTabs()
}

/** First login of a new team member: the temporary password must be replaced before anything else. */
export function passwordPage(root, user, onDone) {
  const msg = h('div')
  const current = h('input', { type: 'password', autocomplete: 'current-password', required: true })
  const next = h('input', { type: 'password', autocomplete: 'new-password', required: true })
  const again = h('input', { type: 'password', autocomplete: 'new-password', required: true })
  const btn = h('button', { type: 'submit', text: 'Save my password' })
  fill(root, h('div', { class: 'login-wrap' },
    h('section', { class: 'login-art' },
      h('div', { class: 'logo' }, h('span', { class: 'mark' }, icon('bolt', 16)), h('span', {}, 'TechDeva Audit', h('small', { text: 'Gulf & South Asia audits' }))),
      h('div', {}, h('h2', { text: `Welcome to the team, ${user.name.split(' ')[0]}.` }),
        h('p', { text: 'You logged in with a temporary password from your admin. Pick your own one — only you will know it.' })),
      h('div')),
    h('div', { class: 'login rv' },
      h('h1', { text: 'Set your password' }),
      h('p', { class: 'sub', text: 'At least 10 characters, letters and numbers together.' }),
      h('form', { class: 'gap', onsubmit: async (e) => {
        e.preventDefault()
        msg.replaceChildren()
        if (next.value !== again.value) { msg.replaceChildren(banner('bad', 'The two new passwords are not the same')); return }
        btn.disabled = true
        try {
          await api.post('/auth/password', { current: current.value, new: next.value })
          onDone()
        } catch (err) { msg.replaceChildren(banner('bad', err.message)); btn.disabled = false }
      } },
        h('div', { class: 'gap' }, h('label', {}, 'Temporary password', current)),
        h('div', { class: 'gap' }, h('label', {}, 'New password', next)),
        h('div', { class: 'gap' }, h('label', {}, 'New password again', again)),
        h('div', { class: 'gap' }, msg, btn)))))
}
