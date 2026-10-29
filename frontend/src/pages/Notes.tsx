import { Fragment, useEffect, useState } from 'react'
import { api, errorText, type Release } from '@/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n } from '@/i18n'

/** `**bold**` and `code` of the notes, as elements (never as HTML: the text comes from a file, not from a trusted page). */
function Inline({ text }: { text: string }) {
  return (
    <>
      {/* split() with a capture group puts the matches at the ODD indexes: an unclosed "**x" or "`x" is plain text at an even one */}
      {text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) =>
        i % 2 === 1 && part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong>
          : i % 2 === 1 && part.startsWith('`') ?<code key={i} className="rounded bg-slate-100 px-1 text-[0.9em]">{part.slice(1, -1)}</code>
            : <Fragment key={i}>{part}</Fragment>)}
    </>
  )
}

/** The release notes: CHANGELOG.md, newest version first. */
export default function Notes() {
  const { t, msg, date, lang } = useI18n()
  const [releases, setReleases] = useState<Release[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {  // the notes follow the language
    let cancelled = false  // a slower answer for the language the user has left must not replace the one they asked for since
    api.changelog(lang)
      .then((rows) => { if (!cancelled) { setReleases(rows); setError('') } })  // the new language loaded: an old failure is over
      .catch((e) => { if (!cancelled) setError(errorText(e)) })
    return () => { cancelled = true }
  }, [lang])
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
