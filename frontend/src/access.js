import { api } from './api.js'

// What the logged-in person may do and who is on the team; read once per page load, refreshed on change.
let permsCache = null
let teamCache = null

export async function can(user, action) {
  if (user?.role === 'admin') return true
  permsCache ??= await api.get('/team/permissions')
  return Boolean(permsCache.roles[user?.role]?.[action])
}

export async function teamList(fresh = false) {
  if (fresh || !teamCache) teamCache = await api.get('/team')
  return teamCache
}

export function forget() { permsCache = null; teamCache = null }

export const ownerName = (team, id) => (id ? team.find((m) => m.id === id)?.name || 'someone' : null)
