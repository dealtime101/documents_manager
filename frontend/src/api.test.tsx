import { afterEach, expect, test, vi } from 'vitest'
import { api, ApiError, errorText, SettingsRefused } from '@/api'

// DOC534.228: the real request code runs; only fetch (the network) is replaced.
afterEach(() => vi.unstubAllGlobals())

const answer = (rows: unknown[], total: string | null) =>
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(rows), { status: 200, headers: total === null ? {} : { 'X-Total-Count': total } })))

test('the total count of the queue is a whole number, or else the number of rows received', async () => {
  for (const [header, expected] of [['40', 40], ['', 2], [' ', 2], ['abc', 2], ['-1', 2], ['1.5', 2], [null, 2]] as const) {
    answer([{ id: 1 }, { id: 2 }], header)
    expect((await api.items()).total).toBe(expected)
  }
})

test('a network that is down reaches the screens as an ApiError, not as a raw TypeError', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
  const failure = await api.history().catch((e) => e)
  expect(failure).toBeInstanceOf(ApiError)
  expect(failure.message).toBe('Network error: the server cannot be reached.')
})

test('the CSRF token sent is everything after the cookie name, even when the value holds an equals sign', async () => {
  document.cookie = 'csrftoken=abc==def; path=/'
  const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  await api.ignore(1)
  expect(fetcher.mock.calls[0][1].headers['X-CSRFToken']).toBe('abc==def')
  document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
})

test('saving the settings on a lost network is a translated ApiError, and a refused one carries the field errors', async () => {
  const values = { inbox: 'a', library_root: 'b', quarantine: '', extra_inboxes: [], watch_inbox: false }
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
  const lost = await api.saveSettings(values).catch((e) => e)
  expect(lost).toBeInstanceOf(ApiError)
  expect(lost.message).toBe('Network error: the server cannot be reached.')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ errors: { inbox: 'Not a folder.' } }), { status: 400 })))
  const refused = await api.saveSettings(values).catch((e) => e)
  expect(refused).toBeInstanceOf(SettingsRefused)
  expect(Object.keys(refused.errors)).toEqual(['inbox'])
})

test('an error that is not an ApiError is logged and shown as a generic message, never as a raw exception text', () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => {})
  expect(errorText(new TypeError('secret internals'))).toBe('Unexpected error.')
  expect(log).toHaveBeenCalledTimes(1)
  expect(errorText(new ApiError('Known.'))).toBe('Known.')
  log.mockRestore()
})

test('a refusal of the server keeps its status and its body for the caller', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'no way' }), { status: 403 })))
  const failure = await api.history().catch((e) => e)
  expect(failure).toBeInstanceOf(ApiError)
  expect(failure.status).toBe(403)
  expect(failure.body).toEqual({ detail: 'no way' })
  expect(failure.message).toBe('no way')
})
