import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { LibraryListing, LibraryPlan } from '@/api'
import { I18nProvider } from '@/i18n'
import Library from '@/pages/Library'

// DOC534.228: the explorer is rendered and used; only the server (api) is replaced.
const m = vi.hoisted(() => ({
  library: vi.fn(), libraryPlan: vi.fn(), libraryApply: vi.fn(), libraryDelete: vi.fn(), libraryRename: vi.fn(), libraryMove: vi.fn(),
  librarySearch: vi.fn(), libraryNewFolder: vi.fn(), vocabulary: vi.fn(), destinations: vi.fn(), expired: vi.fn(),
}))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, ...m } }
})

const listing = (path: string, folders: string[], files: string[]): LibraryListing => ({
  path, parent: path.split('/').slice(0, -1).join('/'), is_root: path === '', folders, truncated: false,
  files: files.map((name) => ({ name, size: 2048, modified: 1_700_000_000 })),
})
const fields = (company: string) => ({ company, document_type: 'Invoice', date: '2024-01-01', detail: '', amount: '', currency: 'CAD' })
const plan = (company: string): LibraryPlan => ({ fields: fields(company), final_name: `${company}.pdf`, rel_dir: `Bills/${company}`, current_dir: '', current_name: '' })
const show = () => render(<I18nProvider><Library /></I18nProvider>)

beforeEach(() => {
  localStorage.setItem('docflow.lang', 'en')
  for (const f of Object.values(m)) f.mockReset()
  m.library.mockImplementation(async (path: string) => (path === '' ? listing('', ['Tax'], ['a.pdf', 'b.pdf']) : listing(path, [], [])))
  m.vocabulary.mockResolvedValue({ companies: [], types: [] })
  m.destinations.mockResolvedValue([])
  m.libraryDelete.mockResolvedValue({ path: null, permanent: false })
})
afterEach(() => { cleanup(); vi.useRealTimers() })

const open = async (name: string) => fireEvent.click(await screen.findByRole('button', { name: new RegExp(name) }))
const company = () => screen.getByLabelText('Company') as HTMLInputElement

test('a deletion is asked in the page first, with the focus on Cancel, and only the confirmation deletes', async () => {
  show()
  await open('a.pdf')
  fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
  const dialog = screen.getByRole('alertdialog')
  expect(dialog.textContent).toContain('Put “a.pdf” in the _Trash folder?')
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }))     // a stray Enter deletes nothing
  expect(m.libraryDelete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(m.libraryDelete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  fireEvent.click(screen.getByRole('button', { name: 'OK' }))
  await waitFor(() => expect(m.libraryDelete).toHaveBeenCalledWith('a.pdf'))
})

test('a proposal read for one file never fills the form of another, nor shows its error there', async () => {
  let forA: (v: LibraryPlan) => void = () => {}
  let failB: (e: unknown) => void = () => {}
  m.libraryPlan.mockReturnValueOnce(new Promise((done) => { forA = done })).mockReturnValueOnce(new Promise((_, no) => { failB = no }))
  show()
  await open('a.pdf')
  fireEvent.click(await screen.findByRole('button', { name: 'Read the document and propose' }))
  await open('b.pdf')                                                   // the list stays clickable while A is read
  await act(async () => { forA(plan('Acme')) })
  expect(company().value).toBe('')                                      // B's form is not filled with A's proposal
  fireEvent.click(await screen.findByRole('button', { name: 'Read the document and propose' }))
  await open('a.pdf')                                                   // back to A while B's reading is still on its way
  await act(async () => { failB(new Error('boom')) })
  expect(screen.queryByText(/Unexpected error/)).toBeNull()             // B's failure is not shown on A
})

// the plan is asked 400 ms after the last edit: fake timers, every step flushed by hand
const flush = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const typeCompany = (value: string) => fireEvent.change(company(), { target: { value } })

test('Apply waits for a preview computed for what is typed now, and a proposal does not trigger a second request', async () => {
  vi.useFakeTimers()
  m.libraryPlan.mockImplementation(async (_file: string, f?: { company: string }) => plan(f?.company ?? 'Acme'))
  m.libraryApply.mockResolvedValue({ path: 'Bills/Acme/Acme.pdf', learned: [] })
  show()
  await flush()
  fireEvent.click(screen.getByRole('button', { name: /a\.pdf/ }))
  await flush()
  fireEvent.click(screen.getByRole('button', { name: 'Read the document and propose' }))
  await flush()
  await flush(1000)                                                     // long after the proposal: the effect must not ask again
  expect(m.libraryPlan).toHaveBeenCalledTimes(1)
  const apply = screen.getByRole('button', { name: 'Apply: rename and move' }) as HTMLButtonElement
  expect(apply.disabled).toBe(false)
  typeCompany('Beta')
  expect(apply.disabled).toBe(true)                                     // the old "will be" line is not offered for the NEW fields
  expect(screen.queryByText('Will be filed as:')).toBeNull()
  await flush(400)
  expect(m.libraryPlan).toHaveBeenCalledTimes(2)
  expect(apply.disabled).toBe(false)
  expect(screen.getByText('Bills/Beta/Beta.pdf')).toBeTruthy()
  fireEvent.click(apply)
  await flush()
  expect(m.libraryApply.mock.calls[0][1]).toMatchObject({ company: 'Beta' })
})

test('the move picker builds paths from the folder its list was read for, not from the one being loaded', async () => {
  m.library.mockImplementation(async (path: string) => (path === '' ? listing('', ['Tax', 'Bills'], ['a.pdf']) : new Promise(() => {})))
  show()
  await open('a.pdf')
  fireEvent.click(await screen.findByRole('button', { name: 'Move' }))
  fireEvent.click(await screen.findByRole('button', { name: /📁 Tax/ }))   // the picker's own button; "Tax" is loading and never arrives
  m.library.mockClear()
  fireEvent.click(screen.getByRole('button', { name: /📁 Bills/ }))     // still the root's list on screen
  await waitFor(() => expect(m.library).toHaveBeenCalledWith('Bills'))
  expect(m.library).not.toHaveBeenCalledWith('Tax/Bills')
})

test('the folder actions wait for the running change like the file actions', async () => {
  let done: (v: unknown) => void = () => {}
  m.library.mockImplementation(async (path: string) => (path === 'Tax' ? listing('Tax', [], ['t.pdf']) : listing('', ['Tax'], ['a.pdf'])))
  m.libraryRename.mockReturnValue(new Promise((resolve) => { done = resolve }))
  show()
  fireEvent.click(await screen.findByRole('button', { name: /Tax/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Rename folder' }))
  fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Taxes' } })
  fireEvent.click(screen.getByRole('button', { name: 'OK' }))
  await waitFor(() => expect(m.libraryRename).toHaveBeenCalled())
  for (const name of ['New folder', 'Rename folder', 'Move folder', 'Delete folder']) {
    expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
  }
  await act(async () => { done({ path: 'Taxes' }) })
})
