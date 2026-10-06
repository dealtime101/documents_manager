import { useEffect, useState } from 'react'
import { api, errorText, SettingsRefused, type FolderListing } from '@/api'
import { Field, Notice } from '@/components/Bits'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'

/** A list of sub-folders to walk through: the browser cannot open a native folder dialog, so the server lists them. */
function Picker({ start, onPick, onClose }: { start: string; onPick: (path: string) => void; onClose: () => void }) {
  const { t, msg } = useI18n()
  const [list, setList] = useState<FolderListing | null>(null)
  const [error, setError] = useState('')
  const [target, setTarget] = useState<string | undefined>(start || undefined)  // the folder being shown: changing it loads its list
  useEffect(() => {
    let current = true
    api.folders(target).then((l) => { if (current) { setList(l); setError('') } }).catch((e) => { if (current) setError(errorText(e)) })
    return () => { current = false }
  }, [target])
  return (
    <div className="mt-1 rounded-md border bg-slate-50 p-2 text-sm">
      {error && <p role="alert" className="text-rose-700">{msg(error)}</p>}
      {list && (
        <>
          <p className="mb-1 break-all font-mono text-xs">{list.path}</p>
          <div className="mb-1 flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setTarget(list.parent)}>{t('settings.up')}</Button>
            <Button type="button" size="sm" onClick={() => onPick(list.path)}>{t('settings.useThis')}</Button>
            <Button type="button" variant="outline" size="sm" onClick={onClose}>{t('settings.close')}</Button>
          </div>
          <ul className="max-h-48 overflow-auto">
            {list.folders.map((name) => (
              <li key={name}><button type="button" className="w-full rounded px-1 py-0.5 text-left hover:bg-slate-200"
                onClick={() => setTarget(`${list.path.replace(/[\\/]$/, '')}${list.path.includes('\\') ? '\\' : '/'}${name}`)}>{name}</button></li>
            ))}
            {list.folders.length === 0 && <li className="text-slate-500">{t('settings.noSub')}</li>}
          </ul>
        </>
      )}
    </div>
  )
}

type Values = { inbox: string; library_root: string; quarantine: string; extra: string }
const KEYS = [['inbox', 'settings.inbox'], ['library_root', 'settings.library'], ['quarantine', 'settings.quarantine']] as const

/** Where the documents are: the folders to watch and to file into. The first screen of a new install. */
export default function Settings({ onSaved }: { onSaved: () => void }) {
  const { t, msg } = useI18n()
  const [v, setV] = useState<Values | null>(null)
  const [first, setFirst] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [picking, setPicking] = useState<keyof Values | null>(null)
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.settings().then((s) => {
      setFirst(!s.configured)
      setV({ inbox: s.configured ? s.inbox : '', library_root: s.configured ? s.library_root : '', quarantine: s.configured ? s.quarantine ?? '' : '', extra: s.extra_inboxes.join('\n') })
    }).catch((e) => setNote({ ok: false, text: errorText(e) }))
  }, [])
  if (!v) return note ? <p role="alert" className="text-rose-700">{msg(note.text)}</p> : <p role="status" className="text-slate-500">{t('common.loading')}</p>
  const set = (k: keyof Values, value: string) => setV({ ...v, [k]: value })
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErrors({})
    try {
      await api.saveSettings({ inbox: v.inbox.trim(), library_root: v.library_root.trim(), quarantine: v.quarantine.trim(),
        extra_inboxes: v.extra.split('\n').map((x) => x.trim()).filter(Boolean) })
      setNote({ ok: true, text: t('settings.saved') })
      setFirst(false)
      onSaved()
    } catch (x) {
      if (x instanceof SettingsRefused) setErrors(x.errors)
      else setNote({ ok: false, text: msg(errorText(x)) })
    }
    setBusy(false)
  }
  return (
    <Card>
      <CardHeader><CardTitle as="h2">{t('nav.settings')}</CardTitle></CardHeader>
      <CardContent>
        {first && <p className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-900">{t('settings.welcome')}</p>}
        <form onSubmit={save} className="max-w-2xl space-y-3">
          {KEYS.map(([key, label]) => (
            <div key={key}>
              <Field label={t(label)}>
                <Input value={v[key]} onChange={(e) => set(key, e.target.value)} placeholder={key === 'quarantine' ? t('settings.helpQuarantine') : ''}
                  aria-invalid={errors[key] ? true : undefined} aria-describedby={errors[key] ? `err-${key}` : undefined} />
              </Field>
              <Button type="button" variant="outline" size="sm" className="mt-1" onClick={() => setPicking(picking === key ? null : key)}>{t('settings.browse')}</Button>
              {errors[key] && <p id={`err-${key}`} role="alert" className="text-sm text-rose-700"><span aria-hidden="true">✕ </span>{errors[key]}</p>}
              {picking === key && <Picker start={v[key]} onPick={(p) => { set(key, p); setPicking(null) }} onClose={() => setPicking(null)} />}
            </div>
          ))}
          <div>
            <label className="text-sm font-medium" htmlFor="extra-inboxes">{t('settings.extra')}</label>
            <textarea id="extra-inboxes" className="mt-1 w-full rounded-md border p-2 font-mono text-sm" rows={3} value={v.extra} onChange={(e) => set('extra', e.target.value)} />
            {Object.entries(errors).filter(([k]) => k.startsWith('extra_inboxes')).map(([k, m]) => <p key={k} role="alert" className="text-sm text-rose-700">{m}</p>)}
          </div>
          <Button type="submit" disabled={busy} aria-busy={busy}>{t('settings.save')}</Button>
          <Notice note={note} />
        </form>
      </CardContent>
    </Card>
  )
}
