import { useState } from 'react'
import { api, errorText, type SearchFilters, type SearchHit } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'

/** The snippet of a hit with its words found (marked \x01...\x02 by the server) shown as <mark>: built as elements, never as HTML. */
function Snippet({ text }: { text: string }) {
  return (
    <p className="text-sm text-slate-600">
      {text.split('\x01').map((part, i) => {
        const [hit, rest] = i === 0 ? [null, part] : part.split('\x02')
        return <span key={i}>{hit !== null && <mark className="rounded bg-yellow-200 px-0.5">{hit}</mark>}{rest}</span>
      })}
    </p>
  )
}

const NO_FILTERS: SearchFilters = { company: '', type: '', date_from: '', date_to: '', amount_min: '', amount_max: '', sort: 'relevance' }
const SORTS = ['relevance', 'date', '-date', 'amount', '-amount'] as const
const SORT_LABELS = { relevance: 'search.sortRelevance', date: 'search.sortDateUp', '-date': 'search.sortDateDown',
  amount: 'search.sortAmountUp', '-amount': 'search.sortAmountDown' } as const

/** Search of the filed documents: by the words in their text (read when they were scanned) and/or by the fields read from each
 * (company, type, period, amount). Nothing leaves the machine. */
export default function Search() {
  const { t, msg, date } = useI18n()
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<SearchFilters>(NO_FILTERS)
  const [hits, setHits] = useState<SearchHit[] | null>(null)  // null: nothing searched yet
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const narrowed = Object.entries(filters).some(([key, value]) => key !== 'sort' && value.trim() !== '')
  const canSearch = query.trim() !== '' || narrowed
  const setFilter = (key: keyof SearchFilters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setFilters((f) => ({ ...f, [key]: e.target.value }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy || !canSearch) return
    setBusy(true)
    setError('')
    setHits(null)  // the previous results are not the answer to this query: if it fails they must not stay under the error
    try {
      setHits(await api.search(query, filters))
    } catch (x) {
      setError(errorText(x))
    }
    setBusy(false)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{t('search.hint')}</p>
      <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-64 flex-1 flex-col gap-1 text-sm font-medium">{t('search.label')}
          <Input autoFocus type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Button type="submit" disabled={busy || !canSearch}>{busy ? t('common.loading') : t('search.go')}</Button>
      </div>
      <div role="group" aria-label={t('search.filters')} className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <label className="flex flex-col gap-1 text-sm font-medium">{t('search.company')}
          <Input value={filters.company} onChange={setFilter('company')} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">{t('search.type')}
          <Input value={filters.type} onChange={setFilter('type')} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">{t('search.dateFrom')}
          <Input type="date" value={filters.date_from} onChange={setFilter('date_from')} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">{t('search.dateTo')}
          <Input type="date" value={filters.date_to} onChange={setFilter('date_to')} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">{t('search.amountMin')}
          <Input type="number" inputMode="decimal" min="0" step="0.01" value={filters.amount_min} onChange={setFilter('amount_min')} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">{t('search.amountMax')}
          <Input type="number" inputMode="decimal" min="0" step="0.01" value={filters.amount_max} onChange={setFilter('amount_max')} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">{t('search.sort')}
          <select value={filters.sort} onChange={setFilter('sort')}
            className="h-8 w-full rounded-lg border border-field bg-transparent px-2 text-sm dark:bg-input/30">
            {SORTS.map((s) => <option key={s} value={s}>{t(SORT_LABELS[s])}</option>)}
          </select>
        </label>
        <div className="flex items-end">
          <Button type="button" variant="outline" disabled={busy || (!narrowed && filters.sort === 'relevance')}
            onClick={() => setFilters(NO_FILTERS)}>{t('search.clear')}</Button>
        </div>
      </div>
      </form>
      {/* live regions present before their text, so a result count or an error is announced */}
      <div role="status" className="empty:hidden text-sm text-slate-600">
        {hits !== null && !error && (hits.length ? t('search.count', { n: hits.length }) : t('search.none'))}
      </div>
      <div role="alert" className="empty:hidden text-sm text-rose-700">{error && msg(error)}</div>
      <ul className="space-y-2">
        {(hits ?? []).map((h) => (
          <li key={h.id} className="rounded-md border p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <strong className="min-w-0 break-words">{h.filename}</strong>
              <a className="text-sm text-blue-700 underline" href={api.pdfUrl(h.id)} target="_blank" rel="noreferrer"
                aria-label={t('search.openLabel', { name: h.filename })}>{t('search.open')}</a>
            </div>
            <p className="text-xs text-slate-500">{[h.company, h.document_type, h.date && date(h.date),
              h.amount && `${h.amount} ${h.currency ?? ''}`.trim(), h.folder].filter(Boolean).join(' · ')}</p>
            {h.snippet && <Snippet text={h.snippet} />}
          </li>
        ))}
      </ul>
    </div>
  )
}
