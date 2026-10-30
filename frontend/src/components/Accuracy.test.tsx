import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import Accuracy from '@/components/Accuracy'
import { I18nProvider } from '@/i18n'

// DOC534.228: the card is rendered and used; only the server (api) is replaced.
const { stats } = vi.hoisted(() => ({ stats: vi.fn() }))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, stats } }
})

const figures = { total: 10, untouched: 8, fields: [], months: [], companies: [{ company: 'A very long company name that ends in an ellipsis', total: 4, corrected: 2 }],
  bands: [], threshold: { current: 0.95, suggested: null, documents: 0, newly_automatic: 0 } }
const show = () => render(<I18nProvider><Accuracy /></I18nProvider>)

beforeEach(() => { localStorage.setItem('docflow.lang', 'en'); stats.mockReset() })
afterEach(cleanup)

test('the status region is in the page before its text, and says when the figures arrived', async () => {
  let done: (v: unknown) => void = () => {}
  stats.mockReturnValue(new Promise((resolve) => { done = resolve }))
  const { container } = show()
  const region = container.querySelector('p[role="status"]')!
  expect(region.textContent).toBe('Loading…')
  done(figures)
  await waitFor(() => expect(region.textContent).toBe('Accuracy figures loaded.'))
  expect(region.isConnected).toBe(true)                                // the same element, only its text changed
})

test('a truncated label can still be read in full', async () => {
  stats.mockResolvedValue(figures)
  show()
  const label = await screen.findByText('A very long company name that ends in an ellipsis')
  expect(label.getAttribute('title')).toBe('A very long company name that ends in an ellipsis')
})

test('the retry button stays where it is while the new try runs, cannot be repeated, and the focus goes to the title once it worked', async () => {
  stats.mockRejectedValueOnce(new Error('boom'))
  show()
  const retry = await screen.findByRole('button', { name: 'Try again' })
  retry.focus()
  let done: (v: unknown) => void = () => {}
  stats.mockReturnValue(new Promise((resolve) => { done = resolve }))
  fireEvent.click(retry)
  fireEvent.click(retry)                                               // a second click while the first try runs
  expect(stats).toHaveBeenCalledTimes(2)                               // the first load, and one retry
  expect(screen.getByRole('button', { name: 'Try again' })).toBe(retry)   // still there, under the focus
  expect(retry.getAttribute('aria-disabled')).toBe('true')
  expect(document.activeElement).toBe(retry)
  done(figures)
  await waitFor(() => expect(document.activeElement?.id).toBe('accuracy-title'))
})
