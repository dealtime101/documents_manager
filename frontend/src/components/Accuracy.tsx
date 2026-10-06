import { useCallback, useEffect, useState } from 'react'
import { type Accuracy as Stats, api, errorText } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n, type AskKey } from '@/i18n'

const FIELD_LABEL: Record<Stats['fields'][number]['field'], AskKey> = {
  company: 'field.company', document_type: 'field.type', date: 'field.date', amount: 'field.amount',
  detail: 'field.detail', destination: 'field.destination',
}

/** How often the engine's proposals were accepted as they were: by field, month, company and confidence band. */
export default function Accuracy() {
  const { t, msg, percent, month } = useI18n()
  const [s, setS] = useState<Stats | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api.stats().then((r) => { setS(r); setError('') })
    .catch((e) => setError(errorText(e))), [])
  useEffect(() => { load() }, [load])

  // decorative: the numbers beside it say the same thing. Green is a share ACCEPTED, amber a share CORRECTED.
  const bar = (ratio: number, tone: string) => (
    <span aria-hidden="true" className="inline-block h-2 w-28 shrink-0 rounded bg-slate-200">
      <span className={`block h-2 rounded ${tone}`} style={{ width: `${Math.round(ratio * 100)}%` }} />
    </span>
  )
  const GOOD = 'bg-emerald-600'
  const BAD = 'bg-amber-500'
  const row = (key: string, label: string, text: string, ratio: number, tone = GOOD) => (
    <li key={key} className="flex items-center justify-between gap-3 border-b py-1 last:border-0">
      <span className="min-w-0 truncate" title={label}>{label}</span>
      <span className="flex shrink-0 items-center gap-2"><span className="text-slate-600">{text}</span>{bar(ratio, tone)}</span>
    </li>
  )
  const heading = (text: string) => <h3 className="mb-1 mt-3 text-sm font-medium text-slate-600">{text}</h3>

  let body: React.ReactNode
  if (error) {
    body = (
      <div role="alert" className="space-y-2">
        <p className="text-rose-700">{msg(error)}</p>
        <Button variant="outline" size="sm" onClick={() => { setError(''); void load() }}>{t('common.retry')}</Button>
      </div>
    )
  } else if (!s) {
    body = <p className="text-slate-500">{t('common.loading')}</p>
  } else if (s.total === 0) {
    body = <p className="text-slate-500">{t('acc.none')}</p>
  } else {
    const th = s.threshold
    body = (
      <>
        <p>{t('acc.summary', { n: s.total, untouched: s.untouched, rate: percent(s.untouched / s.total) })}</p>
        {heading(t('acc.fields'))}
        <ul>{s.fields.map((f) => row(f.field, t(FIELD_LABEL[f.field]), t('acc.fieldCount', { n: f.corrected, total: f.total }),
          f.total ? f.corrected / f.total : 0, BAD))}</ul>
        {heading(t('acc.months'))}
        <ul>{s.months.map((m) => row(m.month, month(m.month), t('acc.untouchedCount', { n: m.untouched, total: m.total }), m.total ? m.untouched / m.total : 0))}</ul>
        {s.companies.some((c) => c.corrected > 0) && (<>
          {heading(t('acc.companies'))}
          <ul>{s.companies.filter((c) => c.corrected > 0).map((c) => row(c.company, c.company,
            t('acc.fieldCount', { n: c.corrected, total: c.total }), c.corrected / c.total, BAD))}</ul>
        </>)}
        {heading(t('acc.bands'))}
        <ul>{s.bands.filter((b) => b.total > 0).map((b) => row(b.band, t('acc.band', { band: b.band }),
          t('acc.untouchedCount', { n: b.untouched, total: b.total }), b.untouched / b.total))}</ul>
        <p className="mt-3 rounded bg-slate-50 p-2 text-slate-700">
          {th.suggested === null
            ? t('acc.noSuggest', { current: percent(th.current) })
            : t('acc.suggest', { documents: th.documents, suggested: percent(th.suggested), fresh: th.newly_automatic, current: percent(th.current) })}
        </p>
      </>
    )
  }
  return (
    <Card>
      <CardHeader><CardTitle as="h2">{t('acc.title')}</CardTitle></CardHeader>
      <CardContent className="text-sm">
        {/* a live region that is in the page BEFORE its text arrives (a region that appears with its text is often not read) */}
        <p role="status" className="sr-only">{!s && !error ? t('common.loading') : s ? t('acc.loaded') : ''}</p>
        {body}
      </CardContent>
    </Card>
  )
}
