import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { Confidence, NameInput, Notice, StatusBadge } from '@/components/Bits'
import { I18nProvider } from '@/i18n'

// DOC534.228: the shared pieces are rendered, not read as text.
const wrap = (node: React.ReactNode) => <I18nProvider>{node}</I18nProvider>

beforeEach(() => localStorage.setItem('docflow.lang', 'en'))
afterEach(cleanup)

test('both live regions are in the page while empty, are not hidden, and tell success from failure', () => {
  const { container, rerender } = render(<Notice note={null} />)
  const status = container.querySelector('[role="status"]')!
  const alert = container.querySelector('[role="alert"]')!
  expect(status.textContent).toBe('')
  expect(alert.textContent).toBe('')
  expect(status.className).not.toContain('empty:hidden')
  expect(alert.className).not.toContain('empty:hidden')
  rerender(<Notice note={{ ok: true, text: 'Done.' }} />)
  expect(status.textContent).toContain('Done.')                       // the same region element: text added to a region already there
  expect(alert.textContent).toBe('')
  rerender(<Notice note={{ ok: false, text: 'Refused.' }} />)
  expect(alert.textContent).toContain('Refused.')
  expect(status.textContent).toBe('')
})

test('the same message shown twice in a row is a new element, so it is announced again', () => {
  const { container, rerender } = render(<Notice note={{ ok: true, text: 'Saved.' }} />)
  const first = container.querySelector('[role="status"] p')!
  rerender(<Notice note={{ ok: true, text: 'Saved.' }} />)             // a new note object with the same words
  const second = container.querySelector('[role="status"] p')!
  expect(second).not.toBe(first)
  rerender(<Notice note={{ ok: true, text: 'Saved.' }} />)
  expect(container.querySelector('[role="status"] p')).not.toBe(second)
})

test('the same note object, rendered again, is not announced again', () => {
  const note = { ok: true, text: 'Saved.' }
  const { container, rerender } = render(<Notice note={note} />)
  const first = container.querySelector('[role="status"] p')!
  rerender(<Notice note={note} />)
  expect(container.querySelector('[role="status"] p')).toBe(first)
})

test('the fixed extension is read with the field, and a typed extension is not doubled', () => {
  const changes: string[] = []
  render(wrap(<NameInput value="" onChange={(v) => changes.push(v)} />))
  const field = screen.getByRole('textbox')
  const described = document.getElementById(field.getAttribute('aria-describedby')!)!
  expect(described.textContent).toContain('Extension added automatically:')
  expect(described.textContent).toContain('.pdf')
  expect(described.closest('[aria-hidden="true"]')).toBeNull()         // not hidden from screen readers
  fireEvent.change(field, { target: { value: 'Bill' } })
  fireEvent.change(field, { target: { value: 'Bill.PDF' } })
  expect(changes).toEqual(['Bill.pdf', 'Bill.pdf'])
  cleanup()
  render(wrap(<NameInput value="Bill.pdf" onChange={(v) => changes.push(v)} />))
  expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('Bill')   // the stem only: the extension is beside it
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '' } })
  expect(changes.at(-1)).toBe('')                                      // an empty box means "automatic"
})

test('a long status label is cut by CSS and stays readable in the title; an unknown status is shown as it is', () => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  render(wrap(<><StatusBadge status="auto" /><StatusBadge status={'constructor' as never} /></>))
  const known = screen.getByTitle('Automatic')                          // the whole label on hover
  expect(known.querySelector('.truncate')?.textContent).toBe('Automatic')
  const unknown = screen.getByTitle('constructor')                      // not taken for a known status of Object
  expect(unknown.textContent).toBe('constructor')
  expect(unknown.className).toContain('bg-rose-100')                    // the fallback style
})

test('a confidence level is given by a symbol and a word, not only by its colour', () => {
  const item = { confidence: 0.99, conf: { date: 0.9, company: 0.5 } } as never
  const { container } = render(wrap(<Confidence item={item} thresholds={{ auto: 0.95, confirm: 0.8 }} />))
  const text = container.textContent!
  expect(text).toContain('✓ 99%')                                       // a symbol, seen
  expect(text).toContain('(high confidence)')                           // a word, heard
  expect(text).toContain('! 90%')
  expect(text).toContain('(medium confidence')
  expect(text).toContain('✕ 50%')
  expect(text).toContain('(low confidence)')
  expect([...container.querySelectorAll('[aria-hidden="true"]')].map((n) => n.textContent?.trim())).toEqual(['✓', '!', '✕'])
  expect(container.querySelectorAll('.sr-only').length).toBeGreaterThanOrEqual(3)
})
