import './style.css'
import { api, onAuthLost } from './api.js'
import { h, icon, skeleton } from './ui.js'
import { overview } from './pages/overview.js'
import { search } from './pages/search.js'
import { leads } from './pages/leads.js'
import { leadDetail } from './pages/leadDetail.js'
import { reportPage } from './pages/reportViewer.js'
import { monitor } from './pages/monitor.js'
import { results } from './pages/results.js'
import { outreach } from './pages/outreach.js'
import { settings } from './pages/settings.js'
import { activity } from './pages/activity.js'
import { loginPage, passwordPage } from './pages/login.js'
import { mywork } from './pages/mywork.js'
import { calling } from './pages/calling.js'
import { assignCity } from './pages/assignCity.js'
import { teamPage } from './pages/team.js'
import { forget } from './access.js'

// [key, label, minimum role, icon, group]
const NAV = [
  ['overview', 'Overview', 'viewer', 'overview', ''],
  ['search', 'Lead Search', 'admin', 'search', 'Find'],
  ['leads', 'All Leads', 'viewer', 'leads', 'Qualify'],
  ['results', 'Audit Results', 'viewer', 'results', 'Qualify'],
  ['calls', 'My calls', 'sales', 'phone', 'Calling'],
  ['desk', 'Calling desk', 'admin', 'leads', 'Calling'],
  ['mywork', 'My work', 'sales', 'calendar', 'Sell'],
  ['outreach', 'Outreach (Harvey)', 'viewer', 'phone', 'Sell'],
  ['team', 'Team', 'viewer', 'leads', 'Team'],
  ['monitor', 'Agent Monitor', 'admin', 'monitor', 'System'],
  ['settings', 'Settings', 'viewer', 'settings', 'System'],
  ['activity', 'Activity log', 'admin', 'activity', 'System'],
]
const RANK = { viewer: 0, sales: 1, admin: 2 }

const app = document.querySelector('#app')
const main = h('main', { id: 'main' })
const nav = h('nav', { 'aria-label': 'Main' })
const who = h('div', { class: 'who' })
const aside = h('aside', {},
  h('a', { class: 'logo', href: '#/overview', 'aria-label': 'TechDeva Audit, overview' },
    h('span', { class: 'mark' }, icon('bolt', 16)), h('span', {}, 'TechDeva Audit', h('small', { text: 'Gulf & South Asia audits' }))),
  nav, who)
const shell = h('div', { class: 'shell' }, aside, main)

let user = null
let stopPage = null // pages may return a cleanup function (timers)
export const currentUser = () => user

function showLogin() {
  user = null
  if (typeof stopPage === 'function') stopPage()
  stopPage = null
  app.replaceChildren()
  forget()
  loginPage(app, (u) => { user = u; route() })
}

onAuthLost(showLogin)

const initials = (name) => (name || '?').split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase()

function drawNav(page) {
  // a caller only has the calling desk; everyone else sees what their rank allows
  const allowed = user.role === 'caller' ? NAV.filter(([key]) => key === 'calls') : NAV.filter(([, , role]) => RANK[user.role] >= RANK[role])
  const items = []
  let group = null
  for (const [key, label, , ico, g] of allowed) {
    if (g !== group) { if (g) items.push(h('div', { class: 'nav-label', text: g })); group = g }
    items.push(h('a', { href: `#/${key}`, class: key === page ? 'on' : '', 'aria-current': key === page ? 'page' : null }, icon(ico), label))
  }
  nav.replaceChildren(...items)
  who.replaceChildren(h('span', { class: 'avatar', text: initials(user.name), title: user.name }),
    h('div', { class: 'meta' }, h('div', { class: 'small', text: user.name }), h('div', { class: 'small mute', text: user.role })),
    h('button', { class: 'ghost icon-only', title: 'Log out', 'aria-label': 'Log out',
      onclick: async () => { await api.post('/auth/logout'); showLogin() } }, icon('logout')))
}

async function route() {
  if (!user) {
    try { user = await api.get('/auth/me') } catch { return showLogin() }
  }
  if (user.must_change_password) {
    app.replaceChildren()
    return passwordPage(app, user, () => { user = { ...user, must_change_password: false }; route() })
  }
  if (!app.contains(shell)) app.replaceChildren(shell)
  let [page = 'overview', id, sub] = location.hash.replace(/^#\/?/, '').split('?')[0].split('/')
  if (user.role === 'caller' && page !== 'calls') { page = 'calls'; id = undefined; sub = undefined }
  drawNav(page === 'reports' ? 'results' : page)
  if (typeof stopPage === 'function') stopPage()
  stopPage = null
  main.classList.remove('swap')
  main.replaceChildren(skeleton())
  try {
    if (page === 'search') stopPage = await search(main)
    else if (page === 'leads' && id) stopPage = await leadDetail(main, Number(id), user, sub)
    else if (page === 'leads') stopPage = await leads(main, user)
    else if (page === 'reports' && id) stopPage = await reportPage(main, id)
    else if (page === 'results') stopPage = await results(main, user, id)
    else if (page === 'outreach') stopPage = await outreach(main, user)
    else if (page === 'mywork') stopPage = await mywork(main, user)
    else if (page === 'calls') stopPage = await calling(main, user)
    else if (page === 'desk') stopPage = await assignCity(main, user)
    else if (page === 'team') stopPage = await teamPage(main, user, id)
    else if (page === 'monitor') stopPage = await monitor(main)
    else if (page === 'settings') stopPage = await settings(main, user, id)
    else if (page === 'activity') stopPage = await activity(main)
    else stopPage = await overview(main, user)
  } catch (err) {
    if (user) main.replaceChildren(h('div', { class: 'banner bad', text: `Could not load: ${err.message}` }))
  }
  void main.offsetWidth // restart the page-in animation
  main.classList.add('swap')
  window.scrollTo({ top: 0 })
}

window.addEventListener('hashchange', route)
route()
