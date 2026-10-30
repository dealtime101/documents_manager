import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { I18nProvider } from '@/i18n'
import Rules from '@/pages/Rules'

// DOC534.228: the page is rendered and used; only the server (api) is replaced.
const { rules, forgetRule, setRoute } = vi.hoisted(() => ({ rules: vi.fn(), forgetRule: vi.fn(), setRoute: vi.fn() }))
vi.mock('@/api', async (original) => {
  const real = await original<typeof import('@/api')>()
  return { ...real, api: { ...real.api, rules, forgetRule, setRoute } }
})

const learned = (routes = [{ company: 'Acme', destination: 'Bills/Acme', filed: 3 }]) => ({
  aliases: [{ company: 'Beta', patterns: ['beta inc', 'beta ltd'], filed: 2 }], types: [], routes,
})
const show = () => render(<I18nProvider><Rules /></I18nProvider>)
const field = () => screen.getByLabelText('Destination of Acme') as HTMLInputElement
const type = (value: string) => fireEvent.change(field(), { target: { value } })
const submit = () => fireEvent.submit(field().closest('form')!)

beforeEach(() => {
  localStorage.setItem('docflow.lang', 'en')
  vi.stubGlobal('confirm', () => true)
  rules.mockReset().mockResolvedValue(learned())
  forgetRule.mockReset().mockResolvedValue({ forgotten: true })
  setRoute.mockReset().mockResolvedValue({})
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('two clicks before the next render ask for one change only', async () => {
  let finish: (v: unknown) => void = () => {}
  forgetRule.mockReturnValue(new Promise((done) => { finish = done }))
  show()
  const [one, two] = await screen.findAllByRole('button', { name: /Forget the pattern .* of Beta/ })
  act(() => { one.click(); two.click() })        // both before React re-renders: the state `busy` is still false for the second
  expect(forgetRule).toHaveBeenCalledTimes(1)
  finish({ forgotten: true })
  await screen.findByText('Rule forgotten.')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Forget the rule of Acme' })).toHaveProperty('disabled', false))  // lock let go
})

test('Enter in the destination saves the trimmed value; an unchanged or empty one saves nothing; Forget never submits', async () => {
  show()
  await screen.findByLabelText('Destination of Acme')
  const save = screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement
  expect(save.disabled).toBe(true)                      // nothing typed yet
  type('  Bills/Acme  ')
  expect(save.disabled).toBe(true)                      // a change of spaces alone is no edit
  submit()
  type('   ')
  submit()
  expect(setRoute).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Forget the rule of Acme' }))   // type="button": it asks to forget, never saves
  expect(setRoute).not.toHaveBeenCalled()
  await waitFor(() => expect(forgetRule).toHaveBeenCalledTimes(1))
  await screen.findByText('Rule forgotten.')
  type('  Bills/Hydro ')
  submit()
  await waitFor(() => expect(setRoute).toHaveBeenCalledWith('Acme', 'Bills/Hydro'))
  await screen.findByText('Destination corrected.')
})

test('a saved destination stays on screen until the rules are reloaded, and when the reload fails too, with both messages', async () => {
  show()
  await screen.findByLabelText('Destination of Acme')
  let reloaded: (v: unknown) => void = () => {}
  rules.mockReturnValueOnce(new Promise((done) => { reloaded = done }))
  type('Bills/Hydro')
  submit()
  await screen.findByText('Destination corrected.')
  expect(field().value).toBe('Bills/Hydro')                     // not the old destination while the reload runs
  reloaded(learned([{ company: 'Acme', destination: 'Bills/Hydro', filed: 3 }]))
  await waitFor(() => expect((screen.getByLabelText('Destination of Acme') as HTMLInputElement).value).toBe('Bills/Hydro'))
  rules.mockRejectedValueOnce(new Error('boom'))
  type('Bills/Water')
  submit()
  const alert = await screen.findByRole('alert')
  await waitFor(() => expect(alert.textContent).toContain('Unexpected error.'))
  expect(screen.getByText('Beta')).toBeTruthy()                  // the list stays: a failed refresh does not replace the page
  expect(field().value).toBe('Bills/Water')                      // and the typing is kept: the reload did not read the saved value
})

test('forgetting a route also forgets the unsaved typing for that company', async () => {
  show()
  await screen.findByLabelText('Destination of Acme')
  type('half typed')
  rules.mockResolvedValueOnce(learned([]))                      // the route is gone after the first forget...
  fireEvent.click(screen.getByRole('button', { name: 'Forget the rule of Acme' }))
  await waitFor(() => expect(screen.queryByLabelText('Destination of Acme')).toBeNull())
  rules.mockResolvedValue(learned())                            // ...and learned again: the field shows what was learned
  fireEvent.click(screen.getAllByRole('button', { name: /Forget the pattern .* of Beta/ })[0])
  await waitFor(() => expect(field().value).toBe('Bills/Acme'))
})

test('each forget button of an alias pattern has its own accessible name', async () => {
  show()
  await screen.findByLabelText('Destination of Acme')
  expect(screen.getByRole('button', { name: 'Forget the pattern "beta inc" of Beta' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Forget the pattern "beta ltd" of Beta' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Forget the rule of Acme' })).toBeTruthy()
})

test('a failed first load replaces the page with an error and a way to try again', async () => {
  rules.mockRejectedValueOnce(new Error('boom'))
  show()
  expect((await screen.findByRole('alert')).textContent).toContain('Unexpected error.')
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByLabelText('Destination of Acme')
})
