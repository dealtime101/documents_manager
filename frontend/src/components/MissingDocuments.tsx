import { useCallback, useEffect, useState } from 'react'
import { api, errorText, type Missing } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n } from '@/i18n'

/** The documents that usually come at a steady rhythm (a monthly bill) and have not come, with a way to stop hearing about one. */
export default function MissingDocuments() {
  const { t, msg, date } = useI18n()
  const [m, setM] = useState<Missing | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)  // a click is being answered: a second one would repeat it
  const load = useCallback(() => api.missing().then((r) => { setM(r); setError('') }).catch((e) => setError(errorText(e))), [])
  useEffect(() => { void load() }, [load])
  const change = async (run: () => Promise<Missing>) => {
    if (busy) return
    setBusy(true)
    try { setM(await run()); setError('') } catch (e) { setError(errorText(e)) }
    setBusy(false)
  }

  let body: React.ReactNode
  if (!m) {
    body = error
      ? <div role="alert" className="space-y-2"><p className="text-rose-700">{msg(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void load()}>{t('common.retry')}</Button></div>
      : <p className="text-slate-500">{t('common.loading')}</p>
  } else {
    body = (
      <>
        {/* a change that failed keeps the list on screen and says so */}
        <p role="alert" className="empty:hidden text-rose-700">{error && msg(error)}</p>
        {m.missing.length === 0 && <p className="text-slate-500">{t('missing.none')}</p>}
        <ul>
          {m.missing.map((s) => (
            <li key={JSON.stringify([s.company, s.document_type])} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-0">
              <span className="min-w-0">
                <strong className="break-words">{s.company}</strong> · {s.document_type}
                <span className="block text-slate-600">
                  {t('missing.row', { n: s.days_late, expected: date(s.expected_date), every: s.every_days, last: date(s.last_date) })}
                </span>
              </span>
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void change(() => api.ignoreMissing(s.company, s.document_type))}
                aria-label={t('missing.ignoreLabel', { company: s.company, type: s.document_type })}>{t('missing.ignore')}</Button>
            </li>
          ))}
        </ul>
        {m.ignored.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer text-slate-600">{t('missing.ignored', { n: m.ignored.length })}</summary>
            <ul>
              {m.ignored.map((s) => (
                <li key={JSON.stringify([s.company, s.document_type])} className="flex flex-wrap items-center justify-between gap-2 py-1">
                  <span className="min-w-0 break-words">{s.company} · {s.document_type}</span>
                  <Button variant="outline" size="sm" disabled={busy} onClick={() => void change(() => api.restoreMissing(s.company, s.document_type))}
                    aria-label={t('missing.restoreLabel', { company: s.company, type: s.document_type })}>{t('missing.restore')}</Button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </>
    )
  }
  return (
    <Card>
      <CardHeader><CardTitle as="h2">{t('missing.title')}</CardTitle></CardHeader>
      <CardContent className="text-sm">
        <p className="mb-2 text-slate-600">{t('missing.hint')}</p>
        {body}
      </CardContent>
    </Card>
  )
}
