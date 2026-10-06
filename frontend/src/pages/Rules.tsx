import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, errorText, type LearnedRules } from '@/api'
import { Notice } from '@/components/Bits'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'

type Kind = 'alias' | 'type' | 'route'

/** What the program learned from corrections: look at it, forget it, correct a destination. The hand-written rules are not
 *  here and cannot be changed from here (the server only ever touches the learned files). */
export default function Rules() {
  const { t, msg } = useI18n()
  const [rules, setRules] = useState<LearnedRules | null>(null)
  const [loadError, setLoadError] = useState('')
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})  // a destination being edited, by company

  // true when the rules were read: a caller can then drop what it was holding on to (a draft) without showing a stale value
  const haveRules = useRef(false)  // the rules were read at least once: a later failed reload must not replace the whole page
  const [reloadError, setReloadError] = useState('')
  const load = useCallback(() => api.rules().then((r) => {
    haveRules.current = true
    setRules(r); setLoadError(''); setReloadError('')
    return true
  }).catch((e) => {
    const text = errorText(e)
    if (haveRules.current) setReloadError(text)  // keep the list (and what was just saved) on screen, say the refresh failed
    else setLoadError(text)
    return false
  }), [])
  useEffect(() => { load() }, [load])

  const act = async (action: () => Promise<unknown>, done: string, after?: () => void) => {
    if (busy) return  // one change at a time
    setBusy(true)
    try {
      await action()
      setNote({ ok: true, text: done })
      const loaded = await load()
      if (loaded) after?.()  // only once the saved value is what the screen reads: no flash of the old one, no stale one if it failed
    } catch (e) {
      setNote({ ok: false, text: msg(errorText(e)) })
    } finally {
      setBusy(false)
    }
  }
  const forget = (kind: Kind, company: string, pattern?: string) => {
    if (confirm(t('rules.confirmForget', { what: pattern ? `${company} / “${pattern}”` : company }))) void act(() => api.forgetRule(kind, company, pattern), t('rules.forgotten'))
  }
  const saveRoute = (company: string, destination: string) => act(
    () => api.setRoute(company, destination), t('rules.routeSaved'),
    () => setDrafts((d) => { const next = { ...d }; delete next[company]; return next }))  // back to the saved value, after the reload

  // the same object until its inputs change: Notice treats a new object as a new message to announce
  const shownNote = useMemo(
    () => (reloadError ? { ok: false, text: `${note?.ok ? `${note.text} ` : ''}${msg(reloadError)}` } : note),
    [reloadError, note, msg])
  const filed = (n: number) => <span className="text-xs text-slate-500">{t('rules.filed', { n })}</span>
  const forgetButton = (kind: Kind, company: string, pattern?: string) => (
    <Button variant="outline" size="sm" disabled={busy} aria-label={pattern ? t('rules.forgetPatternLabel', { company, pattern }) : t('rules.forgetLabel', { company })}
      onClick={() => forget(kind, company, pattern)}>{t('rules.forget')}</Button>
  )
  const section = (title: string, help: string, empty: boolean, rows: React.ReactNode) => (
    <Card>
      <CardHeader><CardTitle as="h2">{title}</CardTitle><p className="text-sm text-slate-500">{help}</p></CardHeader>
      <CardContent className="space-y-2 text-sm">
        {empty ? <p className="text-slate-500">{t('rules.none')}</p> : rows}
      </CardContent>
    </Card>
  )

  if (loadError) {
    return (
      <div role="alert" className="space-y-2">
        <p className="text-rose-700">{msg(loadError)}</p>
        <Button variant="outline" size="sm" onClick={() => { setLoadError(''); void load() }}>{t('common.retry')}</Button>
      </div>
    )
  }
  if (!rules) return <p role="status" className="text-slate-500">{t('common.loading')}</p>

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{t('rules.intro')}</p>
      <Notice note={shownNote} />
      {section(t('rules.aliases'), t('rules.aliasesHelp'), rules.aliases.length === 0, rules.aliases.map((a) => (
        <div key={a.company} className="rounded-md border p-2">
          <div className="flex items-center justify-between gap-2"><strong>{a.company}</strong>{filed(a.filed)}</div>
          <ul className="mt-1 space-y-1">
            {a.patterns.map((p) => (
              <li key={p} className="flex items-center justify-between gap-2">
                <code className="min-w-0 truncate rounded bg-slate-100 px-1 text-xs" title={p}>{p}</code>
                {forgetButton('alias', a.company, p)}
              </li>
            ))}
          </ul>
        </div>
      )))}
      {section(t('rules.types'), t('rules.typesHelp'), rules.types.length === 0, rules.types.map((r) => (
        <div key={r.company} className="flex items-center justify-between gap-2 rounded-md border p-2">
          <span><strong>{r.company}</strong> → {r.type}</span>
          <span className="flex items-center gap-2">{filed(r.filed)}{forgetButton('type', r.company)}</span>
        </div>
      )))}
      {section(t('rules.routes'), t('rules.routesHelp'), rules.routes.length === 0, rules.routes.map((r) => {
        const value = drafts[r.company] ?? r.destination
        return (
          <div key={r.company} className="space-y-1 rounded-md border p-2">
            <div className="flex items-center justify-between gap-2"><strong>{r.company}</strong>{filed(r.filed)}</div>
            <div className="flex flex-wrap items-center gap-2">
              <Input className="min-w-48 flex-1" value={value} aria-label={t('rules.destinationOf', { company: r.company })}
                onChange={(e) => { const next = e.target.value; setDrafts((d) => ({ ...d, [r.company]: next })) }} />
              <Button size="sm" disabled={busy || value.trim() === r.destination || !value.trim()} onClick={() => saveRoute(r.company, value.trim())}>
                {t('rules.save')}
              </Button>
              {forgetButton('route', r.company)}
            </div>
          </div>
        )
      }))}
    </div>
  )
}
