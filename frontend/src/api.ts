// REST client. A file path is never sent to the server: only fields; the server recomputes names and folders.
export interface Item {
  id: number
  state: string
  status: 'auto' | 'confirm' | 'manual' | 'duplicate' | 'logical_duplicate' | 'error'
  filename: string
  company: string | null
  document_type: string | null
  date: string
  detail: string
  amount: string | null
  currency: string
  invoice_number: string | null
  conf: Record<string, number>
  confidence: number
  final_name: string
  rel_dir: string
  destination: string
  notes: string[]
  extraction: string
  result_path: string
}

export interface Dashboard {
  pending: number
  needs_validation: number
  auto_ready: number
  duplicates: number
  errors: number
  classified_today: number
  sources: { kind: 'inbox' | 'backlog'; path: string; files: number }[]
  history: Operation[]
}

/** How often the engine's proposals were accepted without a correction, from the documents already filed. */
export interface Accuracy {
  total: number
  untouched: number
  fields: { field: 'company' | 'document_type' | 'date' | 'amount' | 'detail' | 'destination'; corrected: number; total: number }[]
  months: { month: string; total: number; untouched: number }[]
  companies: { company: string; total: number; corrected: number }[]
  bands: { band: string; total: number; untouched: number }[]
  threshold: { current: number; suggested: number | null; documents: number; newly_automatic: number }
}

/** A filed document that contains the words searched for. `snippet` marks each word found between \x01 and \x02. */
export interface SearchHit {
  id: number
  filename: string
  folder: string
  company: string | null
  date: string | null
  snippet: string
}

/** A rule the program learned from a correction (the hand-written ones are not part of this list). */
export interface LearnedRules {
  aliases: { company: string; patterns: string[]; filed: number }[]
  types: { company: string; type: string; filed: number }[]
  routes: { company: string; destination: string; filed: number }[]
}

export interface Operation {
  id: number
  kind: string
  ts: string
  undone: number
  src: string
  dst: string
}

/** What the engine retained from a correction (rendered in the user's language by the UI). */
export interface Learned {
  kind: 'company' | 'type' | 'route'
  value: string
  company: string
}

export interface ScanJob {
  state: 'none' | 'running' | 'done' | 'error'
  total: number
  done: number
  created: number
  skipped: number
  error: string
}

/** The answer of a bulk approval: what was filed, and every id that was not (with the reason). */
export type Batch = { approved: number[]; failed: { id: number; detail: string }[]; remaining?: number }  // remaining: the limit of one request was reached

/** The four disjoint categories of pending documents: the dashboard counts them, the queue can be limited to one. */
export type Group = 'auto' | 'needs_validation' | 'duplicates' | 'errors'

/** The engine's cut-offs: a score at or above `auto` is filed on its own, at or above `confirm` it asks, below it is manual. */
export interface Thresholds { auto: number; confirm: number }
/** What the screen assumes until the server has answered (the values of config/settings.yaml as shipped). */
export const DEFAULT_THRESHOLDS: Thresholds = { auto: 0.95, confirm: 0.8 }

/** The folders in use (Settings screen). `configured` is false on a first run: none was chosen yet. */
export interface FolderSettings {
  configured: boolean
  inbox: string
  library_root: string
  quarantine: string
  extra_inboxes: string[]
}
export interface FolderListing { path: string; parent: string; folders: string[] }
export interface LibraryHit { name: string; path: string; folder: string; is_dir: boolean; size: number; modified: number }
/** The fields of the "classify" form of a library PDF (all text; amount '' = none). */
export interface LibraryFields { company: string; document_type: string; date: string; detail: string; amount: string; currency: string }
export interface LibraryPlan { fields: LibraryFields; final_name: string; rel_dir: string; current_dir: string; current_name: string }
/** A folder of the library (paths are relative to the library, with `/`). */
export interface LibraryListing {
  path: string; parent: string; is_root: boolean; folders: string[]; truncated: boolean
  files: { name: string; size: number; modified: number }[]
}
/** A refused save: `errors` names the setting and says what is wrong with it. */
export class SettingsRefused extends Error {
  errors: Record<string, string>
  constructor(errors: Record<string, string>) {
    super(Object.values(errors).join(' '))
    this.errors = errors
  }
}

/** One version of the release notes (CHANGELOG.md): its sections hold the items, `**bold**` and `code` still marked in the text. */
export interface Release {
  version: string
  date: string
  intro: string
  sections: { title: string; items: string[] }[]
}

export class ApiError extends Error {
  status?: number  // the HTTP status, when the server answered at all
  constructor(message: string, status?: number) {
    super(message)
    this.status = status
  }
}

/** The text to show for a failure. An ApiError carries a message made for the user (translated afterwards by msg()). Anything
 *  else is a bug of the page, not something to put raw in front of the reader: the detail goes to the console for the developer
 *  and the screen shows a generic message. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  console.error(e)
  return 'Unexpected error.'
}

function csrf(): string {
  const c = document.cookie.split('; ').find((c) => c.startsWith('csrftoken='))
  return c ? c.slice('csrftoken='.length) : ''  // everything after the name: a value may itself contain "="
}

/** Every readable string of an error body, with the field it concerns: `{"amount": ["bad"]}` -> "amount: bad". */
function messages(v: unknown, field = ''): string[] {
  if (typeof v === 'string') return [field ? `${field}: ${v}` : v]
  if (Array.isArray(v)) return v.flatMap((x) => messages(x, field))
  if (v && typeof v === 'object') {
    return Object.entries(v).flatMap(([k, x]) => messages(x, k === 'detail' || k === 'non_field_errors' ? field : field ? `${field}.${k}` : k))
  }
  return []  // numbers, booleans, null: nothing a person can read
}

/** The text shown for a failed request: the server's message(s), whatever shape the error body has (never "[object Object]"). */
export function errorMessage(data: unknown, status: number): string {
  const found = messages(data)
  return found.length ? found.join(' ') : `HTTP error: ${status}`
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  return (await request<T>(method, url, body)).data
}

async function request<T>(method: string, url: string, body?: unknown): Promise<{ data: T; total: number | null }> {
  let r: Response
  try {
    r = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {  // fetch rejects with a bare TypeError ("Failed to fetch") when the server cannot be reached at all
    throw new ApiError('Network error: the server cannot be reached.')
  }
  // `undefined` when the body is not JSON (HTML from a proxy or captive portal, truncated answer, empty body)
  const data = await r.json().catch(() => undefined)
  if (!r.ok) throw new ApiError(errorMessage(data, r.status), r.status)
  if (data === undefined) throw new ApiError(`unexpected response from the server: HTTP ${r.status}`)  // every endpoint answers JSON
  const total = r.headers.get('X-Total-Count')
  // a whole number, or null: '' is 0 and 'abc' is NaN for Number(), and `?? data.length` replaces neither
  return { data: data as T, total: total !== null && /^\d+$/.test(total) ? Number(total) : null }
}

export const api = {
  me: () => call<{ authenticated: boolean; username: string | null; version: string }>('GET', '/api/auth/me'),
  localLogin: (token: string) => call('POST', '/api/auth/local', { token }),  // the desktop launcher's one-time token
  // `total` is the size of the whole queue: larger than rows.length when the server capped the list
  items: async (state = 'pending', group?: Group) => {
    const query = new URLSearchParams({ state })
    if (group) query.set('group', group)  // one of the dashboard's categories: same definition on the server
    const { data, total } = await request<Item[]>('GET', `/api/items?${query}`)
    return { rows: data, total: total ?? data.length }
  },
  save: (id: number, fields: Record<string, unknown>) => call<Item>('PATCH', `/api/items/${id}`, fields),
  approve: (id: number) => call<{ item: Item; learned: Learned[]; learning_failed: boolean }>('POST', `/api/items/${id}/approve`),
  ignore: (id: number) => call('POST', `/api/items/${id}/ignore`),
  remove: (id: number) => call('POST', `/api/items/${id}/remove`),
  scan: () => call<{ job: ScanJob }>('POST', '/api/scan'),
  scanStatus: () => call<ScanJob>('GET', '/api/scan/status'),
  approveAuto: () => call<Batch>('POST', '/api/items/approve-auto'),
  search: (q: string) => call<SearchHit[]>('GET', `/api/search?${new URLSearchParams({ q })}`),
  stats: () => call<Accuracy>('GET', '/api/stats'),
  rules: () => call<LearnedRules>('GET', '/api/rules'),
  forgetRule: (kind: 'alias' | 'type' | 'route', company: string, pattern?: string) =>
    call<{ forgotten: boolean }>('POST', '/api/rules/forget', { kind, company, pattern }),
  setRoute: (company: string, destination: string) => call('POST', '/api/rules/route', { company, destination }),
  approveSelected: (ids: number[]) => call<Batch>('POST', '/api/items/approve-selected', { ids }),
  dashboard: () => call<Dashboard>('GET', '/api/dashboard'),
  history: () => call<Operation[]>('GET', '/api/history'),
  changelog: (lang: string) => call<Release[]>('GET', `/api/changelog?lang=${lang}`),
  thresholds: () => call<Thresholds>('GET', '/api/thresholds'),
  settings: () => call<FolderSettings>('GET', '/api/settings'),
  saveSettings: async (values: Omit<FolderSettings, 'configured'>) => {
    const r = await fetch('/api/settings', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(values) })
    const data = await r.json().catch(() => undefined)
    if (r.status === 400 && data?.errors) throw new SettingsRefused(data.errors as Record<string, string>)
    if (!r.ok) throw new ApiError(errorMessage(data, r.status), r.status)
    return data as FolderSettings
  },
  folders: (path?: string) => call<FolderListing>('GET', `/api/folders${path ? `?${new URLSearchParams({ path })}` : ''}`),
  library: (path = '') => call<LibraryListing>('GET', `/api/library?${new URLSearchParams({ path })}`),
  librarySearch: (q: string) => call<{ hits: LibraryHit[]; truncated: boolean }>('GET', `/api/library/search?${new URLSearchParams({ q })}`),
  libraryNewFolder: (parent: string, name: string) => call<{ path: string }>('POST', '/api/library/folder', { parent, name }),
  libraryRename: (path: string, name: string) => call<{ path: string }>('POST', '/api/library/rename', { path, name }),
  libraryMove: (path: string, to: string) => call<{ path: string }>('POST', '/api/library/move', { path, to }),
  libraryDelete: (path: string) => call<{ path: string | null; permanent: boolean }>('POST', '/api/library/delete', { path }),
  /** Without `fields` the server reads the document and proposes them; with them it only computes the name and folder. */
  libraryPlan: (path: string, fields?: LibraryFields, rel_dir = '', final_name = '') =>
    call<LibraryPlan>('POST', '/api/library/plan', { path, fields, rel_dir, final_name }),
  libraryApply: (path: string, fields: LibraryFields, rel_dir = '', final_name = '') =>
    call<{ path: string; learned: Learned[] }>('POST', '/api/library/apply', { path, fields, rel_dir, final_name }),
  libraryFileUrl: (path: string) => `/api/library/file?${new URLSearchParams({ path })}`,
  undo: (id: number) => call<{ restored: string }>('POST', `/api/history/${id}/undo`),
  destinations: () => call<string[]>('GET', '/api/destinations'),
  vocabulary: () => call<{ companies: string[]; types: string[] }>('GET', '/api/vocabulary'),
  pdfUrl: (id: number) => `/api/items/${id}/pdf`,
}
