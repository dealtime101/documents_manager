import { Fragment, useEffect, useState } from 'react'
import { api, errorText, type Release } from '@/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n } from '@/i18n'

/** `**bold**` and `code` of the notes, as elements (never as HTML: the text comes from a file, not from a trusted page). */
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) =>
        part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong>
          : part.startsWith('`') ? <code key={i} className="rounded bg-slate-100 px-1 text-[0.9em]">{part.slice(1, -1)}</code>
            : <Fragment key={i}>{part}</Fragment>)}
    </>
  )
}

/** The release notes: CHANGELOG.md, newest version first. */
export default function Notes() {
  const { t, msg, date } = useI18n()
  const [releases, setReleases] = useState<Release[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.changelog().then(setReleases).catch((e) => setError(errorText(e))) }, [])
  if (error) return <p role="alert" className="text-rose-700">{msg(error)}</p>
  if (!releases) return <p role="status" className="text-slate-500">{t('common.loading')}</p>
  if (releases.length === 0) return <p className="text-slate-500">{t('notes.none')}</p>
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{t('notes.intro')}</p>
      {releases.map((r, index) => (
        <Card key={r.version}>
          <CardHeader>
            <CardTitle as="h2">
              {t('notes.version', { v: r.version })} <span className="text-sm font-normal text-slate-600">· {date(r.date)}</span>
              {index === 0 && <span className="ml-2 rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">{t('notes.current')}</span>}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {r.intro && <p><Inline text={r.intro} /></p>}
            {r.sections.map((s) => (
              <section key={s.title}>
                <h3 className="mb-1 font-medium">{s.title}</h3>
                <ul className="list-disc space-y-1 pl-5">
                  {s.items.map((item) => <li key={item}><Inline text={item} /></li>)}
                </ul>
              </section>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
