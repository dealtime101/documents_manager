import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { I18nProvider, useI18n } from '@/i18n'
import History from '@/pages/History'

// DOC534.228: the page is rendered and clicked; only the server (api) is replaced.
const { history, undo } = vi.hoisted(() => ({ history: vi.fn(), undo: vi.fn() }))
vi.mock('@/api', async (original) => ({ ...(await original<typeof import('@/api')>()), api: { history, undo } }))

const op = (id: number) => ({ id, kind: 'move', ts: '2026-01-01T10:00:00', undone: 0, src: `C:\\in\\f${id}.pdf`, dst: `C:\\lib\\f${id}.pdf` })
const show = () => render(<I18nProvider><History /></I18nProvider>)

beforeEach(() => {
  localStorage.setItem('docflow.lang', 'en')
  vi.stubGlobal('confirm', () => true)
  history.mockReset().mockResolvedValue([op(1), op(2)])
  undo.mockReset()
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('a second click while an undo is running asks for nothing more', async () => {
  let finish: (v: { restored: string }) => void = () => {}
  undo.mockReturnValue(new Promise((done) => { finish = done }))
  show()
  const first = await screen.findByLabelText(/Undo operation 1 /)
  fireEvent.click(first)
  fireEvent.click(first)
  fireEvent.click(screen.getByLabelText(/Undo operation 2 /))
  expect(undo).toHaveBeenCalledTimes(1)
  expect(undo).toHaveBeenCalledWith(1)
  finish({ restored: 'C:\\in\\f1.pdf' })
  await screen.findByText(/Restored: C:\\in\\f1\.pdf/)
})

test('a failed first load can be tried again from the page, and the loading region is there before its text', async () => {
  history.mockRejectedValueOnce(new Error('boom'))
  const { container } = show()
  const regions = container.querySelectorAll('[role="status"]')
  expect(regions.length).toBeGreaterThan(0)                                    // already in the page while the list loads
  const loading = [...regions].find((r) => r.textContent === 'Loading…' || r.textContent === 'Loading...')
  expect(loading).toBeDefined()
  expect((await screen.findByRole('alert')).textContent).toContain('Unexpected error.')
  expect(loading?.isConnected).toBe(true)                                      // the region stayed, only its text went
  expect(loading?.textContent).toBe('')
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByLabelText(/Undo operation 1 /)
  expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  expect(screen.queryByRole('alert')?.textContent ?? '').toBe('')
})

test('the result of an undo follows a change of language', async () => {
  undo.mockResolvedValue({ restored: 'C:\\in\\f1.pdf' })
  const Switch = () => { const { setLang } = useI18n(); return <button onClick={() => setLang('fr')}>fr</button> }
  render(<I18nProvider><Switch /><History /></I18nProvider>)
  fireEvent.click(await screen.findByLabelText(/Undo operation 1 /))
  await screen.findByText(/Restored: C:\\in\\f1\.pdf/)
  fireEvent.click(screen.getByText('fr'))
  await screen.findByText(/Restauré : C:\\in\\f1\.pdf/)
  expect(screen.queryByText(/Restored:/)).toBeNull()
})

test('after an undo the keyboard focus lands on its row; after a failure the button keeps it', async () => {
  undo.mockResolvedValueOnce({ restored: 'C:\\in\\f1.pdf' }).mockRejectedValueOnce(new Error('boom'))
  show()
  const first = await screen.findByLabelText(/Undo operation 1 /)
  first.focus()
  history.mockResolvedValue([{ ...op(1), undone: 1 }, op(2)])
  fireEvent.click(first)
  await waitFor(() => expect(document.activeElement?.id).toBe('op-1'))         // the button is gone: its row takes the focus
  const second = screen.getByLabelText(/Undo operation 2 /)
  second.focus()
  fireEvent.click(second)
  await screen.findByRole('alert')
  expect(screen.getByLabelText(/Undo operation 2 /)).toBe(second)
  expect(document.activeElement).toBe(second)
  expect(second.getAttribute('aria-disabled')).toBe('false')                   // aria-disabled, not disabled: it stays focusable
})

test('"No operations" is said only after a load that succeeded and came back empty', async () => {
  let done: (v: unknown[]) => void = () => {}
  history.mockReturnValueOnce(new Promise((resolve) => { done = resolve }))
  show()
  expect(screen.queryByText('No operations yet.')).toBeNull()                  // not loaded yet is not "empty"
  await act(async () => { done([]) })
  expect(screen.getByText('No operations yet.')).toBeTruthy()
  cleanup()
  history.mockRejectedValueOnce(new Error('boom'))
  show()
  await screen.findByRole('alert')
  expect(screen.queryByText('No operations yet.')).toBeNull()                  // a failed load is not "empty" either
})

test('an undone operation is named in words, and each undo button names its operation', async () => {
  history.mockResolvedValue([{ ...op(1), undone: 1 }, op(2)])
  const { container } = show()
  await screen.findByLabelText('Undo operation 2 (f2.pdf)')
  expect(screen.queryByLabelText(/Undo operation 1 /)).toBeNull()              // nothing to undo on an undone row
  const row = container.querySelector('#op-1')!
  expect(row.textContent).toContain('Undone')                                  // a word, not only a strike-through
  expect(row.className).toContain('line-through')
  expect(row.innerHTML).not.toContain('text-slate-400')                        // 2.6:1 on white
  expect(container.querySelectorAll('button[aria-label^="Undo operation"]')).toHaveLength(1)
  expect(screen.getByRole('columnheader', { name: 'Action' })).toBeTruthy()    // the action column has a (hidden) header
})

test('the table names itself and ties each header to its column', async () => {
  show()
  await screen.findByLabelText(/Undo operation 1 /)
  const table = screen.getByRole('table', { name: 'History of the filing operations, the latest first' })
  const headers = [...table.querySelectorAll('thead th')]
  expect(headers).toHaveLength(6)
  expect(headers.every((h) => h.getAttribute('scope') === 'col')).toBe(true)
})

test('a failed reload after an undo is shown after the result of the undo, with a way to try again', async () => {
  undo.mockResolvedValue({ restored: 'C:\\in\\f1.pdf' })
  show()
  history.mockRejectedValue(new Error('boom'))
  fireEvent.click(await screen.findByLabelText(/Undo operation 1 /))
  const alert = await screen.findByRole('alert')
  // 'boom' is not a message the page knows: msg() words it
  await waitFor(() => expect(alert.textContent).toMatch(/Restored: C:\\in\\f1\.pdf Unexpected error\./))
  history.mockResolvedValue([op(1), op(2)])
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull())
})
