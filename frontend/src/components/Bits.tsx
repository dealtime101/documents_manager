import { cloneElement, useId, useRef, type ReactElement } from 'react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useI18n, type AskKey } from '@/i18n'
import type { Item, Thresholds } from '@/api'

/** A label tied to its input (htmlFor/id): keyboard- and screen-reader-friendly. */
export function Field({ label, children }: { label: string; children: ReactElement<{ id?: string }> }) {
  const generated = useId()
  const id = children.props.id ?? generated  // an id the caller gave the input is kept (others may point to it)
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      {cloneElement(children, { id })}
    </div>
  )
}

/** A file name typed WITHOUT its extension: the extension is fixed, shown greyed beside the field, and added by the program.
 *  `value` and `onChange` carry the full name ("" while nothing is typed, which means "automatic" where that applies). */
export function NameInput({ value, onChange, ext = '.pdf', placeholder = '', id }: {
  value: string; onChange: (full: string) => void; ext?: string; placeholder?: string; id?: string
}) {
  const strip = (v: string) => (ext && v.toLowerCase().endsWith(ext.toLowerCase()) ? v.slice(0, -ext.length) : v)  // a typed ".pdf" is not doubled
  return (
    <div className="flex items-stretch">
      <Input id={id} className="rounded-r-none" value={strip(value)} placeholder={strip(placeholder)}
        onChange={(e) => { const stem = strip(e.target.value); onChange(stem ? stem + ext : '') }} />
      {ext && <span aria-hidden="true" className="flex select-none items-center rounded-r-md border border-l-0 bg-slate-100 px-2 text-slate-500">{ext}</span>}
    </div>
  )
}

/**
 * The result of an action. Both live regions are ALWAYS in the page, even when empty: a region that appears together
 * with its text is often not announced. Success is polite (`status`), failure is assertive (`alert`); they are siblings,
 * not nested, so nothing is read twice. The icon (hidden from screen readers) keeps the state from relying on colour.
 */
export function Notice({ note }: { note: { ok: boolean; text: string } | null }) {
  // A new notification is a new element (new key) even when its text equals the previous one: React would otherwise leave the
  // DOM alone and a screen reader would not announce the second identical message.
  const last = useRef(note)
  const shown = useRef(0)
  if (note !== last.current) { last.current = note; shown.current += 1 }
  return (
    <>
      <div role="status">
        {note?.ok && <p key={shown.current} className="rounded bg-emerald-50 p-2 text-sm text-emerald-900"><span aria-hidden="true">✓ </span>{note.text}</p>}
      </div>
      <div role="alert">
        {note && !note.ok && <p key={shown.current} className="rounded bg-rose-50 p-2 text-sm text-rose-900"><span aria-hidden="true">✕ </span>{note.text}</p>}
      </div>
    </>
  )
}

const STATUS_CLASS: Record<Item['status'], string> = {
  auto: 'bg-emerald-100 text-emerald-800',
  confirm: 'bg-amber-100 text-amber-800',
  manual: 'bg-rose-100 text-rose-800',
  duplicate: 'bg-slate-200 text-slate-700',
  logical_duplicate: 'bg-orange-100 text-orange-800',
  error: 'bg-red-200 text-red-900',
}

const warned = new Set<string>()

export function StatusBadge({ status }: { status: Item['status'] }) {
  const { t } = useI18n()
  // a status added by a newer server: the fallback style AND a readable label (the raw status), never a missing translation
  const known = Object.hasOwn(STATUS_CLASS, status)  // not `in`: "constructor" and "toString" are "in" every object
  if (!known && !warned.has(status)) { warned.add(status); console.warn(`docflow: unknown item status "${status}"`) }
  const label = known ? t(`status.${status}` as AskKey) : status
  // a long label (a newer server, a wordier language) shrinks with an ellipsis instead of pushing its neighbours out of the
  // row; the title keeps the whole text readable
  return (
    <Badge className={`${known ? STATUS_CLASS[status] : STATUS_CLASS.manual} min-w-0 shrink border-0`} title={label}>
      <span className="truncate">{label}</span>
    </Badge>
  )
}

const FIELDS: [string, AskKey][] = [
  ['date', 'field.date'], ['company', 'field.company'], ['type', 'field.type'], ['detail', 'field.detail'],
  ['amount', 'field.amount'], ['destination', 'field.destination'],
]

/** Overall score plus one score per field, so you can see where a low confidence comes from. */
export function Confidence({ item, thresholds }: { item: Item; thresholds: Thresholds }) {
  const { t, percent } = useI18n()
  // the level is also a symbol (seen) and a word (heard): colour alone leaves out colour-blind readers and screen readers
  const LEVELS = {
    high: { mark: '✓', word: 'conf.high', color: 'text-emerald-700' },
    medium: { mark: '!', word: 'conf.medium', color: 'text-amber-700' },
    low: { mark: '✕', word: 'conf.low', color: 'text-rose-700' },
  } as const satisfies Record<string, { mark: string; word: AskKey; color: string }>
  // the cut-offs are the engine's own (config/settings.yaml, served by /api/thresholds): the colour can never contradict the status
  const band = (v: number) => (v >= thresholds.auto ? LEVELS.high : v >= thresholds.confirm ? LEVELS.medium : LEVELS.low)
  const tone = (v: number | undefined) => (v === undefined ? 'text-slate-500' : band(v).color)
  const level = (v: number | undefined) => (v === undefined ? null : band(v))
  const shown = (v: number | undefined) => {
    const l = level(v)
    return <>{l && <span aria-hidden="true">{l.mark} </span>}{percent(v)}{l && <span className="sr-only"> ({t(l.word)})</span>}</>
  }
  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="font-medium">{t('conf.global')}</span>
        <span className={`text-lg font-semibold ${tone(item.confidence)}`}>{shown(item.confidence)}</span>
      </div>
      {/* a description list: a screen reader pairs each field name with its score */}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        {FIELDS.map(([k, label]) => (
          <div key={k} className="flex justify-between">
            <dt className="text-slate-500">{t(label)}</dt>
            <dd className={tone(item.conf[k])}>{shown(item.conf[k])}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
