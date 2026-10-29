import type { Group } from '@/api'

export type Page = 'dashboard' | 'queue' | 'library' | 'history' | 'search' | 'rules' | 'settings' | 'notes'
export type Route = { page: Page; group: Group | null }

const PAGES: Page[] = ['dashboard', 'queue', 'library', 'history', 'search', 'rules', 'settings', 'notes']
// `satisfies Record<Group, true>` makes the compiler refuse this table when a group is added to (or removed from) the Group type
// in api.ts, instead of parseHash rejecting the new group in silence
const GROUP_KEYS = { auto: true, needs_validation: true, duplicates: true, errors: true } satisfies Record<Group, true>
const GROUPS = Object.keys(GROUP_KEYS) as Group[]

/** `#history`, `#queue`, `#queue/duplicates` (also `#/history`): anything else is the whole queue, the page's default. */
export function parseHash(hash: string): Route {
  const [name, group] = hash.replace(/^#\/?/, '').split('/')
  const page = PAGES.find((p) => p === name) ?? 'queue'
  return { page, group: page === 'queue' ? (GROUPS.find((g) => g === group) ?? null) : null }
}

export const toHash = (route: Route) => `#${route.page}${route.group ? `/${route.group}` : ''}`
