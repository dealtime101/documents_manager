import { useState } from 'react'
import { api, errorText, type SearchHit } from '@/api'
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

/** Full-text search of the filed documents (the text read when they were scanned; nothing leaves the machine). */
export default function Search() {
  const { t, msg, date } = useI18n()
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)  // null: nothing searched yet
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy || !query.trim()) return
    setBusy(true)
    setError('')
    setHits(null)  // the previous results are not the answer to this query: if it fails they must not stay under the error
    try {
      setHits(await api.search(query))
    } catch (x) {
      setError(errorText(x))
    }
    setBusy(false)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{t('search.hint')}</p>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-64 flex-1 flex-col gap-1 text-sm font-medium">{t('search.label')}
          <Input autoFocus type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Button type="submit" disabled={busy || !query.trim()}>{busy ? t('common.loading') : t('search.go')}</Button>
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
            <p className="text-xs text-slate-500">{[h.company, h.date && date(h.date), h.folder].filter(Boolean).join(' · ')}</p>
            <Snippet text={h.snippet} />
          </li>
        ))}
      </ul>
    </div>
  )
}
