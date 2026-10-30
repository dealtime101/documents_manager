import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { I18nProvider } from '@/i18n'
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
