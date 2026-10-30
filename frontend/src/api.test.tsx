import { afterEach, expect, test, vi } from 'vitest'
import { api, ApiError } from '@/api'

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

test('a refusal of the server keeps its status and its body for the caller', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'no way' }), { status: 403 })))
  const failure = await api.history().catch((e) => e)
  expect(failure).toBeInstanceOf(ApiError)
  expect(failure.status).toBe(403)
  expect(failure.body).toEqual({ detail: 'no way' })
  expect(failure.message).toBe('no way')
})
