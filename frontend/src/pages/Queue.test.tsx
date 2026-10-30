import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Item } from '@/api'
import { I18nProvider } from '@/i18n'
import Queue from '@/pages/Queue'

// DOC534.228: the page is rendered and used; only the server (api) is replaced.
const m = vi.hoisted(() => ({
  items: vi.fn(), save: vi.fn(), approve: vi.fn(), approveAuto: vi.fn(), approveSelected: vi.fn(), ignore: vi.fn(),
  scanStatus: vi.fn(), vocabulary: vi.fn(), thresholds: vi.fn(), destinations: vi.fn(),
}))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, ...m } }
})

const item = (id: number, over: Partial<Item> = {}): Item => ({
  id, state: 'pending', status: 'auto', filename: `f${id}.pdf`, company: 'Acme', document_type: 'Invoice', date: '2024-01-01', detail: '',
  amount: null, currency: 'CAD', invoice_number: null, conf: { company: 0.99, document_type: 0.99, date: 0.99, amount: 0.99 }, confidence: 0.99,
  final_name: `Acme ${id}.pdf`, rel_dir: 'Bills', destination: '', notes: [], extraction: 'text', result_path: '', split: null, ...over,
})
const list = (rows: Item[]) => ({ rows, total: rows.length })
const running = { state: 'running', done: 1, total: 5, created: 0, error: '' }
const show = () => render(<I18nProvider><Queue group={null} onShowAll={() => {}} /></I18nProvider>)
const press = (name: string | RegExp) => fireEvent.click(screen.getByRole('button', { name }))
const note = () => (document.querySelector('[role="status"], [role="alert"]') ? [...document.querySelectorAll('[role="status"], [role="alert"]')].map((n) => n.textContent).join(' ') : '')

beforeEach(() => {
  localStorage.setItem('docflow.lang', 'en')
  for (const f of Object.values(m)) f.mockReset()
  m.items.mockResolvedValue(list([item(1), item(2, { status: 'confirm' }), item(3, { status: 'manual' })]))
  m.vocabulary.mockResolvedValue({ companies: [], types: [] })
  m.thresholds.mockResolvedValue({ auto: 0.95, confirm: 0.8 })
  m.destinations.mockResolvedValue([])
  m.scanStatus.mockResolvedValue({ state: 'idle', done: 0, total: 0, created: 0, error: '' })
  m.save.mockResolvedValue({})
  m.approve.mockResolvedValue({ item: item(1), learned: [], learning_failed: false })
  m.approveAuto.mockResolvedValue({ approved: [1], failed: [], remaining: 0 })
  m.approveSelected.mockResolvedValue({ approved: [1, 2], failed: [], remaining: 0 })
  m.ignore.mockResolvedValue({})
  vi.stubGlobal('confirm', vi.fn(() => true))
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })

const company = () => screen.getByLabelText('Company') as HTMLInputElement
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

test('an edit is saved before the approval, and the message is a list of sentences', async () => {
  m.approve.mockResolvedValue({ item: item(1), learned: [{ kind: 'type', value: 'Invoice', company: 'Beta' }], learning_failed: true })
  show()
  await screen.findByLabelText('Company')
  type('Company', 'Beta')
  press('Approve')
  await waitFor(() => expect(m.approve).toHaveBeenCalledWith(1))
  expect(m.save.mock.calls[0][0]).toBe(1)
  expect(m.save.mock.calls[0][1]).toMatchObject({ company: 'Beta' })
  expect(m.save.mock.invocationCallOrder[0]).toBeLessThan(m.approve.mock.invocationCallOrder[0])
  await waitFor(() => expect(note()).toContain('Filed. Remembered for next time: default type “Invoice” for Beta. Warning: the document is filed'))
})

test('an untouched document is approved without a save, and typing in two fields keeps both', async () => {
  show()
  await screen.findByLabelText('Company')
  type('Company', 'Beta')
  type('Date (YYYY-MM-DD, YYYY-MM, YYYY or XXXX)', '2024-02-02')
  expect(company().value).toBe('Beta')
  expect((screen.getByLabelText('Date (YYYY-MM-DD, YYYY-MM, YYYY or XXXX)') as HTMLInputElement).value).toBe('2024-02-02')
  type('Company', 'Acme')
  type('Date (YYYY-MM-DD, YYYY-MM, YYYY or XXXX)', '2024-01-01')
  press('Approve')
  await waitFor(() => expect(m.approve).toHaveBeenCalledWith(1))
  expect(m.save).not.toHaveBeenCalled()
})

test('declining the bulk confirmation changes nothing; accepting files the ticked documents and clears the ticks', async () => {
  show()
  await screen.findByLabelText('Select f1.pdf')
  expect((screen.getByLabelText('Select f3.pdf') as HTMLInputElement).disabled).toBe(true)   // a manual one cannot be filed as it stands
  fireEvent.click(screen.getByLabelText('Select f1.pdf'))
  fireEvent.click(screen.getByLabelText('Select f2.pdf'))
  vi.mocked(confirm).mockReturnValueOnce(false)
  press('Approve selected (2)')
  expect(m.approveSelected).not.toHaveBeenCalled()
  expect(m.items).toHaveBeenCalledTimes(1)                                                    // nothing reloaded
  expect((screen.getByLabelText('Select f1.pdf') as HTMLInputElement).checked).toBe(true)    // the selection stays
  press('Approve selected (2)')
  await waitFor(() => expect(m.approveSelected).toHaveBeenCalledWith([1, 2]))
  await waitFor(() => expect(note()).toContain('2 documents filed.'))
  expect((screen.getByLabelText('Select f1.pdf') as HTMLInputElement).checked).toBe(false)
})

test('a bulk approval asks before dropping an edit, and keeps the open document when it is declined', async () => {
  show()
  await screen.findByLabelText('Select f1.pdf')
  fireEvent.click(screen.getByLabelText('Select f2.pdf'))
  type('Company', 'Beta')
  vi.mocked(confirm).mockImplementation((message) => !String(message).includes('unsaved changes'))   // yes to the batch, no to losing the edit
  press('Approve selected (1)')
  expect(m.approveSelected).not.toHaveBeenCalled()
  expect(company().value).toBe('Beta')
})

test('"approve automatic" goes on after the point where the previous press stopped', async () => {
  m.items.mockResolvedValue(list([item(1)]))
  m.approveAuto.mockResolvedValueOnce({ approved: [1], failed: [], remaining: 5, next_after: 7 })
    .mockResolvedValueOnce({ approved: [], failed: [], remaining: 0 }).mockResolvedValue({ approved: [], failed: [], remaining: 0 })
  show()
  await screen.findByLabelText('Company')
  press('Approve automatic (1)')
  await waitFor(() => expect(m.approveAuto).toHaveBeenCalledTimes(1))
  expect(m.approveAuto).toHaveBeenLastCalledWith(0)
  await waitFor(() => expect(note()).toContain('1 document filed.'))
  press('Approve automatic (1)')
  await waitFor(() => expect(m.approveAuto).toHaveBeenCalledTimes(2))
  expect(m.approveAuto).toHaveBeenLastCalledWith(7)                                           // where the first one stopped
  await waitFor(() => expect(screen.getByRole('button', { name: 'Approve automatic (1)' })).toHaveProperty('disabled', false))
  press('Approve automatic (1)')
  await waitFor(() => expect(m.approveAuto).toHaveBeenCalledTimes(3))
  expect(m.approveAuto).toHaveBeenLastCalledWith(0)                                           // nothing left beyond: from the front again
})

test('a ticked document that stops being approvable leaves the selection', async () => {
  show()
  await screen.findByLabelText('Select f1.pdf')
  fireEvent.click(screen.getByLabelText('Select f1.pdf'))
  expect(screen.getByRole('button', { name: 'Approve selected (1)' })).toBeTruthy()
  m.items.mockResolvedValue(list([item(1, { status: 'error' }), item(2, { status: 'confirm' })]))
  press('Ignore')                                                                             // any action reloads the list
  await waitFor(() => expect(screen.getByRole('button', { name: 'Approve selected (0)' })).toBeTruthy())
  expect((screen.getByLabelText('Select f1.pdf') as HTMLInputElement).checked).toBe(false)
})

test('the one live region of the Queue stays in the page whatever is selected', async () => {
  show()
  await screen.findByLabelText('Company')
  const regions = () => document.querySelectorAll('[role="status"], [role="alert"]').length
  const before = regions()
  const region = document.querySelector('[role="status"]')!
  m.items.mockResolvedValue(list([]))
  press('Ignore')                                                                             // the open document is gone: no form
  await waitFor(() => expect(screen.queryByLabelText('Company')).toBeNull())
  expect(regions()).toBe(before)                                                              // not re-created by the other branch
  expect(document.querySelector('[role="status"]')).toBe(region)
})

// the scan's polling: fake timers, and every step flushed by hand
const tick = () => act(async () => { await vi.advanceTimersByTimeAsync(3000) })
const mount = async () => {
  vi.useFakeTimers()
  m.scanStatus.mockResolvedValue(running)
  show()
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
}

test('a poll that began before an action never brings back the list as it was', async () => {
  m.items.mockResolvedValueOnce(list([item(1), item(2)]))
  await mount()
  let late: (v: unknown) => void = () => {}
  m.items.mockReturnValueOnce(new Promise((done) => { late = done }))                         // the poll's answer, still on its way
  await tick()
  m.items.mockResolvedValue(list([item(2)]))                                                  // after the approval, document 1 is filed
  press('Approve')
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.queryByLabelText('Select f1.pdf')).toBeNull()
  await act(async () => { late(list([item(1), item(2)])); await vi.advanceTimersByTimeAsync(0) })   // the stale answer arrives
  expect(screen.queryByLabelText('Select f1.pdf')).toBeNull()                                 // and is ignored
})

test('the scan refresh keeps a document being edited even when it left the list', async () => {
  m.items.mockResolvedValueOnce(list([item(1), item(2)]))
  await mount()
  type('Company', 'Beta')
  m.items.mockResolvedValue(list([item(2)]))                                                  // document 1 was filed elsewhere
  await tick()
  expect(screen.getByLabelText('Select f1.pdf')).toBeTruthy()                                 // still on top, with what was typed
  expect(company().value).toBe('Beta')
})

test('the scan refresh shows the first document again when the open one left the list and nothing was typed', async () => {
  m.items.mockResolvedValueOnce(list([item(1), item(2, { company: 'Gamma' })]))
  await mount()
  fireEvent.click(screen.getByLabelText('Select f1.pdf'))
  m.items.mockResolvedValue(list([item(2, { company: 'Gamma' })]))
  await tick()
  expect(screen.queryByLabelText('Select f1.pdf')).toBeNull()
  expect(company().value).toBe('Gamma')
})
