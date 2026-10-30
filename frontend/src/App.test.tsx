import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '@/api'
import App from '@/App'

// DOC534.228: the whole application shell is rendered; the pages are stand-ins and only the server (api) is replaced.
const { m, stand } = vi.hoisted(() => ({
  m: { me: vi.fn(), localLogin: vi.fn(), settings: vi.fn() },
  stand: (name: string) => async () => {
    const { createElement } = await import('react')
    return { default: () => createElement('p', null, `${name} page`) }
  },
}))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, ...m } }
})
vi.mock('@/pages/Dashboard', stand('dashboard'))
vi.mock('@/pages/Queue', stand('queue'))
vi.mock('@/pages/Library', stand('library'))
vi.mock('@/pages/History', stand('history'))
vi.mock('@/pages/Search', stand('search'))
vi.mock('@/pages/Rules', stand('rules'))
vi.mock('@/pages/Settings', stand('settings'))
vi.mock('@/pages/Notes', stand('notes'))
vi.mock('@/components/BackupRestore', stand('backup'))

const flush = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const signedIn = { authenticated: true, username: 'me', version: '1.4.2' }

beforeEach(() => {
  localStorage.setItem('docflow.lang', 'en')
  window.history.replaceState(null, '', '/')
  window.location.hash = ''
  for (const f of Object.values(m)) f.mockReset()
  m.me.mockResolvedValue(signedIn)
  m.settings.mockResolvedValue({ configured: true })
  vi.useFakeTimers()
})
afterEach(() => { cleanup(); vi.useRealTimers() })

test('a loading status is shown while the session is checked, not a blank page; a visitor who is not signed in is told what to do', async () => {
  m.me.mockResolvedValue({ authenticated: false, username: null, version: '1.4.2' })
  render(<App />)
  expect(screen.getByRole('status').textContent).toBe('Loading…')
  await flush()
  expect(screen.getByRole('alert').textContent).toContain('Not signed in. Close this window and open the application again.')
})

test('the version the server sent is shown beside the title', async () => {
  render(<App />)
  await flush()
  expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('v1.4.2')
})

test('the title of the document follows the page shown', async () => {
  window.location.hash = '#history'
  render(<App />)
  await flush()
  expect(document.title).toBe('History · Documents Manager')
  act(() => { window.location.hash = '#search'; window.dispatchEvent(new HashChangeEvent('hashchange')) })
  expect(document.title).toBe('Search · Documents Manager')
  fireEvent.click(screen.getByRole('tab', { name: 'To file' }))
  expect(window.location.hash).toBe('#queue')                          // navigation writes the hash; the listener sets the page
})

test('the first run opens the settings, and the check counts as done only once the server answered, trying again if it did not', async () => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  m.settings.mockRejectedValueOnce(new Error('down')).mockRejectedValueOnce(new Error('down')).mockResolvedValue({ configured: false })
  render(<App />)
  await flush()
  expect(m.settings).toHaveBeenCalledTimes(1)
  expect(window.location.hash).not.toBe('#settings')                   // a failed answer is not taken for "configured" either
  await flush(5000)
  expect(m.settings).toHaveBeenCalledTimes(2)
  await flush(5000)
  expect(m.settings).toHaveBeenCalledTimes(3)
  expect(window.location.hash).toBe('#settings')
  await flush(30_000)
  expect(m.settings).toHaveBeenCalledTimes(3)                          // answered: not asked again
})

test('the first-run check gives up after a few tries', async () => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  m.settings.mockRejectedValue(new Error('down'))
  render(<App />)
  await flush()
  for (let i = 0; i < 10; i++) await flush(5000)
  expect(m.settings.mock.calls.length).toBe(5)                         // the first call and four more
})

test('the launcher token stays in the address while the server cannot be reached, and Retry signs in again', async () => {
  window.history.replaceState(null, '', '/?t=secret#queue')
  m.me.mockRejectedValueOnce(new ApiError('Network error: the server cannot be reached.')).mockResolvedValue(signedIn)
  m.localLogin.mockResolvedValue({})
  render(<App />)
  await flush()
  expect(screen.getByRole('alert').textContent).toContain('cannot be reached')
  expect(window.location.search).toBe('?t=secret')                      // still there: Retry must sign in again
  expect(m.localLogin).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await flush()
  expect(m.localLogin).toHaveBeenCalledWith('secret')
  expect(window.location.search).toBe('')                               // out of the address once the server answered
  expect(window.location.hash).toBe('#queue')
  expect(screen.getByRole('heading', { level: 1 })).toBeTruthy()
})

test('a token the server refuses is taken out of the address too, and the session check goes on', async () => {
  window.history.replaceState(null, '', '/?t=stale')
  m.localLogin.mockRejectedValue(new ApiError('Invalid token.', 403))
  render(<App />)
  await flush()
  expect(window.location.search).toBe('')
  expect(m.me).toHaveBeenCalledTimes(2)                                 // once before the token, once for the session
})

test('every tab has a tab panel inside the same tabs root', async () => {
  window.location.hash = '#library'
  render(<App />)
  await flush()
  const tabs = screen.getAllByRole('tab')
  expect(tabs.map((t) => t.textContent)).toEqual(['Dashboard', 'To file', 'Library', 'History', 'Search', 'Rules', 'Settings', 'Release notes'])
  const selected = tabs.find((t) => t.getAttribute('aria-selected') === 'true')!
  const panel = document.getElementById(selected.getAttribute('aria-controls')!)
  expect(panel?.getAttribute('role')).toBe('tabpanel')
  expect(panel?.textContent).toContain('library page')
})
