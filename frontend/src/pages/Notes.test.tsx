import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Release } from '@/api'
import { I18nProvider, LangSwitch } from '@/i18n'
import Notes from '@/pages/Notes'

// DOC534.228: the page is rendered and the language switched; only the server (api) is replaced.
const { changelog } = vi.hoisted(() => ({ changelog: vi.fn() }))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, changelog } }
})

const release = (word: string, items = ['**bold** and `code`']): Release => ({ version: '1.2.3', date: '2026-10-05', intro: `${word} intro`, sections: [{ title: word, items }] })
const show = () => render(<I18nProvider><LangSwitch /><Notes /></I18nProvider>)

beforeEach(() => { localStorage.setItem('docflow.lang', 'en'); changelog.mockReset() })
afterEach(cleanup)

test('the notes of a language left are ignored when their answer comes late', async () => {
  let english: (v: Release[]) => void = () => {}
  changelog.mockReturnValueOnce(new Promise((done) => { english = done })).mockResolvedValueOnce([release('Français')])
  show()
  fireEvent.click(screen.getByRole('button', { name: /^FR|Français/ }))
  await screen.findByText('Français intro')
  await act(async () => { english([release('English')]) })              // the slower answer, for the language left
  expect(screen.queryByText('English intro')).toBeNull()
  expect(screen.getByText('Français intro')).toBeTruthy()
})

test('an old failure is forgotten once the new language has loaded', async () => {
  changelog.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce([release('Français')])
  show()
  expect((await screen.findByRole('alert')).textContent).toContain('Unexpected error.')
  fireEvent.click(screen.getByRole('button', { name: /^FR|Français/ }))
  await screen.findByText('Français intro')
  expect(screen.queryByRole('alert')).toBeNull()
})

test('bold and code are drawn as elements, an unclosed marker stays plain text, and nothing is HTML', async () => {
  changelog.mockResolvedValue([release('Notes', ['**bold** and `code`', '**unclosed at the start and `another', '<b>not html</b>'])])
  const { container } = show()
  await screen.findByText('Notes intro')
  expect(container.querySelector('strong')?.textContent).toBe('bold')
  expect(container.querySelector('code')?.textContent).toBe('code')
  expect(screen.getByText('**unclosed at the start and `another')).toBeTruthy()     // not a <strong> with its first characters cut
  expect(container.querySelector('b')).toBeNull()                       // text from a file is never HTML
  await waitFor(() => expect(container.textContent).toContain('<b>not html</b>'))
})
