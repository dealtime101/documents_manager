import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { I18nProvider } from '@/i18n'
import Search from '@/pages/Search'

// DOC534.228: the page is rendered and used; only the server (api) is replaced.
const { search } = vi.hoisted(() => ({ search: vi.fn() }))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, search } }  // the page also builds links with api.* helpers that need no server
})

const hit = (id: number) => ({ id, filename: `f${id}.pdf`, folder: 'Tax', company: 'Acme', date: '2024-01-01', document_type: 'Invoice', amount: '10', currency: 'CAD', snippet: 'a \x01word\x02 here' })
const show = () => render(<I18nProvider><Search /></I18nProvider>)
const words = () => screen.getByLabelText('Words to look for')

beforeEach(() => { localStorage.setItem('docflow.lang', 'en'); search.mockReset() })
afterEach(cleanup)

test('typing searches nothing; only the submit does, and only once while one is running', async () => {
  let finish: (rows: unknown[]) => void = () => {}
  search.mockReturnValue(new Promise((done) => { finish = done }))
  show()
  const go = screen.getByRole('button', { name: 'Search' })
  expect((go as HTMLButtonElement).disabled).toBe(true)                    // nothing to look for yet
  fireEvent.change(words(), { target: { value: 'invoice' } })
  expect(search).not.toHaveBeenCalled()                                    // typing only edits the text
  fireEvent.submit(words().closest('form')!)
  fireEvent.submit(words().closest('form')!)                               // a second submit while one is in flight
  expect(search).toHaveBeenCalledTimes(1)
  expect(search.mock.calls[0][0]).toBe('invoice')
  expect((screen.getByRole('button', { name: 'Loading…' }) as HTMLButtonElement).disabled).toBe(true)
  finish([hit(1)])
  await screen.findByText('f1.pdf')
})

test('the words found are marked as elements, never as HTML, and the count is announced', async () => {
  search.mockResolvedValue([{ ...hit(1), snippet: 'a \x01<b>word</b>\x02 here' }])
  const { container } = show()
  fireEvent.change(words(), { target: { value: 'word' } })
  fireEvent.submit(words().closest('form')!)
  await screen.findByText('f1.pdf')
  expect(container.querySelector('mark')?.textContent).toBe('<b>word</b>')       // document text: an element, with the tags as plain text
  expect(container.querySelector('b')).toBeNull()
  expect(container.querySelector('[role="status"]')?.textContent).toContain('1')
})

test('a failed search does not leave the results of the previous one on screen', async () => {
  search.mockResolvedValueOnce([hit(1)]).mockRejectedValueOnce(new Error('boom'))
  show()
  fireEvent.change(words(), { target: { value: 'invoice' } })
  fireEvent.submit(words().closest('form')!)
  await screen.findByText('f1.pdf')
  fireEvent.submit(words().closest('form')!)
  expect((await screen.findByRole('alert')).textContent).toBe('Unexpected error.')
  expect(screen.queryByText('f1.pdf')).toBeNull()
})
