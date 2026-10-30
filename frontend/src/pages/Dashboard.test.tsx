import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Dashboard as D } from '@/api'
import { I18nProvider } from '@/i18n'
import Dashboard from '@/pages/Dashboard'

// DOC534.228: the page is rendered and left to refresh by itself; only the server (api) is replaced.
const m = vi.hoisted(() => ({ dashboard: vi.fn(), stats: vi.fn(), missing: vi.fn() }))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, ...m } }
})

const counters = (pending: number): D => ({ pending, needs_validation: 0, auto_ready: 0, duplicates: 0, errors: 0, classified_today: 0, sources: [], history: [] })
const show = () => render(<I18nProvider><Dashboard open={() => {}} /></I18nProvider>)
const flush = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const tile = (n: number) => screen.getByText(String(n), { selector: 'span.text-4xl' })

beforeEach(() => {
  localStorage.setItem('docflow.lang', 'en')
  for (const f of Object.values(m)) f.mockReset()
  m.stats.mockResolvedValue({ total: 0 })
  m.missing.mockResolvedValue({ missing: [], ignored: [] })
  vi.useFakeTimers()
})
afterEach(() => { cleanup(); vi.useRealTimers() })

test('an older answer never overwrites a newer one (the visibility refresh can overlap the scheduled one)', async () => {
  let older: (v: D) => void = () => {}
  m.dashboard.mockReturnValueOnce(new Promise((done) => { older = done })).mockResolvedValue(counters(7))
  show()
  await flush()
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
  document.dispatchEvent(new Event('visibilitychange'))                // a second request starts while the first is in flight
  await flush()
  expect(tile(7)).toBeTruthy()                                         // the newer answer is on screen
  await act(async () => { older(counters(3)); await vi.advanceTimersByTimeAsync(0) })
  expect(tile(7)).toBeTruthy()                                         // and the old one, arriving late, is dropped
  expect(screen.queryByText('3', { selector: 'span.text-4xl' })).toBeNull()
})

test('a failed background refresh keeps the numbers on screen and says they are old', async () => {
  m.dashboard.mockResolvedValueOnce(counters(5)).mockRejectedValue(new Error('boom'))
  show()
  await flush()
  expect(tile(5)).toBeTruthy()
  await flush(15_000)                                                  // the scheduled refresh fails
  expect(tile(5)).toBeTruthy()
  expect(screen.getAllByRole('alert').map((a) => a.textContent).join(' ')).toContain('may be out of date')
})

test('when nothing is on screen yet, a failed refresh is an error with a way to try again, never "Loading" for ever', async () => {
  m.dashboard.mockRejectedValueOnce(new Error('boom'))
  show()
  await flush()
  expect(screen.getByRole('alert').textContent).toContain('Unexpected error.')
  m.dashboard.mockResolvedValue(counters(2))
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await flush()
  expect(tile(2)).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
})

test('a quiet refresh that takes over the first load and fails shows the error, not an empty "Loading"', async () => {
  let first: (v: D) => void = () => {}
  m.dashboard.mockReturnValueOnce(new Promise((done) => { first = done })).mockRejectedValue(new Error('boom'))
  show()
  await flush()
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
  document.dispatchEvent(new Event('visibilitychange'))                // the tab became visible during the first load: a quiet request
  await flush()
  expect(screen.getByRole('alert').textContent).toContain('Unexpected error.')
  await act(async () => { first(counters(1)); await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByRole('alert')).toBeTruthy()                       // the first answer is older than the failed one: dropped
})
