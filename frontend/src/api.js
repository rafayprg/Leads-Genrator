// All calls go to /api, which Vite forwards to FastAPI. No keys ever live in the browser.

let authLost = () => {}
/** main.js registers what to do when the session ends (show the login screen). */
export function onAuthLost(fn) { authLost = fn }

async function request(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && !path.startsWith('/auth/')) authLost()
  if (res.status === 204) return null
  let data = null
  try { data = await res.json() } catch { /* empty body */ }
  if (!res.ok) {
    const d = data?.detail
    const msg = Array.isArray(d) ? d.map((e) => e.msg).join('; ') : (d || `HTTP ${res.status}`)
    throw new Error(msg)
  }
  return data
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b || {}),
  put: (p, b) => request('PUT', p, b || {}),
  patch: (p, b) => request('PATCH', p, b || {}),
  del: (p) => request('DELETE', p),
}

let metaCache = null
export async function meta() {
  metaCache ??= await api.get('/meta')
  return metaCache
}
