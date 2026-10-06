import type { Group } from '@/api'

export type Page = 'dashboard' | 'queue' | 'history' | 'search' | 'rules' | 'settings' | 'notes'
export type Route = { page: Page; group: Group | null }

const PAGES: Page[] = ['dashboard', 'queue', 'history', 'search', 'rules', 'settings', 'notes']
const GROUPS: Group[] = ['auto', 'needs_validation', 'duplicates', 'errors']

/** `#history`, `#queue`, `#queue/duplicates` (also `#/history`): anything else is the whole queue, the page's default. */
export function parseHash(hash: string): Route {
  const [name, group] = hash.replace(/^#\/?/, '').split('/')
  const page = PAGES.find((p) => p === name) ?? 'queue'
  return { page, group: page === 'queue' ? (GROUPS.find((g) => g === group) ?? null) : null }
}

export const toHash = (route: Route) => `#${route.page}${route.group ? `/${route.group}` : ''}`
