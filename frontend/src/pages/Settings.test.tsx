import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { SettingsRefused } from '@/api'
import { I18nProvider } from '@/i18n'
import Settings from '@/pages/Settings'

// DOC534.228: the page is rendered and used; only the server (api) is replaced.
const { settings, saveSettings, folders } = vi.hoisted(() => ({ settings: vi.fn(), saveSettings: vi.fn(), folders: vi.fn() }))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, settings, saveSettings, folders } }
})

const saved = (configured: boolean) => ({ configured, inbox: 'C:\\in', library_root: 'C:\\lib', quarantine: '', extra_inboxes: ['C:\\a', 'C:\\b'], watch_inbox: false })
const show = (onSaved = vi.fn()) => { render(<I18nProvider><Settings onSaved={onSaved} /></I18nProvider>); return onSaved }
const form = async () => (await screen.findByLabelText('Inbox (folder to watch)')).closest('form')!

beforeEach(() => {
  localStorage.setItem('docflow.lang', 'en')
  settings.mockReset().mockResolvedValue(saved(true))
  saveSettings.mockReset().mockResolvedValue({})
  folders.mockReset()
})
afterEach(cleanup)

test('a save leaves the screen only at the end of the first set-up', async () => {
  settings.mockResolvedValue(saved(false))
  const onSaved = show()
  fireEvent.change(await screen.findByLabelText('Inbox (folder to watch)'), { target: { value: 'C:\\in' } })
  fireEvent.submit(await form())
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
  await screen.findByText('Settings saved.')
  fireEvent.submit(await form())                                  // the second save stays where the "saved" message is
  await waitFor(() => expect(saveSettings).toHaveBeenCalledTimes(2))
  await screen.findByText('Settings saved.')
  expect(onSaved).toHaveBeenCalledTimes(1)
})

test('a settled screen never goes on to the queue', async () => {
  const onSaved = show()
  fireEvent.submit(await form())
  await screen.findByText('Settings saved.')
  expect(onSaved).not.toHaveBeenCalled()
})

test('a new save clears the saved message of the previous one, and a refusal names the line of the extra folders', async () => {
  show()
  fireEvent.submit(await form())
  await screen.findByText('Settings saved.')
  let refuse: (e: unknown) => void = () => {}
  saveSettings.mockReturnValue(new Promise((_, reject) => { refuse = reject }))
  fireEvent.submit(await form())
  await waitFor(() => expect(screen.queryByText('Settings saved.')).toBeNull())   // cleared as soon as the new save starts
  refuse(new SettingsRefused({ 'extra_inboxes[1]': 'This folder does not exist.', inbox: 'Not a folder.' }))
  const box = screen.getByLabelText('More folders to watch (one per line)')
  await waitFor(() => expect(box.getAttribute('aria-invalid')).toBe('true'))
  expect(screen.queryByText('Settings saved.')).toBeNull()                         // never beside the errors of this one
  expect(screen.getByText(/Line 2:.*This folder does not exist\./)).toBeTruthy()   // the 2nd entry is on line 2 of the box
  expect(box.getAttribute('aria-describedby')).toBe('err-extra-inboxes')
  expect(screen.getByLabelText('Inbox (folder to watch)').getAttribute('aria-invalid')).toBe('true')
})

test('the folder picker cannot go up from the root, and goes up elsewhere', async () => {
  show()
  await form()
  folders.mockResolvedValue({ path: '/', parent: '/', folders: ['home'] })
  fireEvent.click(screen.getAllByRole('button', { name: 'Browse…' })[0])
  expect((await screen.findByRole('button', { name: 'Parent folder' }) as HTMLButtonElement).disabled).toBe(true)
  folders.mockResolvedValue({ path: '/home', parent: '/', folders: [] })
  fireEvent.click(screen.getByRole('button', { name: 'home' }))
  await waitFor(() => expect((screen.getByRole('button', { name: 'Parent folder' }) as HTMLButtonElement).disabled).toBe(false))
  folders.mockResolvedValue({ path: '/', parent: '/', folders: ['home'] })
  fireEvent.click(screen.getByRole('button', { name: 'Parent folder' }))
  await waitFor(() => expect((screen.getByRole('button', { name: 'Parent folder' }) as HTMLButtonElement).disabled).toBe(true))
})
