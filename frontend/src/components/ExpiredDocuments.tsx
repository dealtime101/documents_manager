import { useCallback, useEffect, useState } from 'react'
import { api, errorText, type Expired } from '@/api'
import { Notice } from '@/components/Bits'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'

/** DOC534.13: the filed documents kept longer than the retention of their type, with a confirmed deletion (to `_Trash`, recorded in History). */
export default function ExpiredDocuments() {
  const { t, msg, date } = useI18n()
  const [data, setData] = useState<Expired | null>(null)
  const [error, setError] = useState('')
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [asking, setAsking] = useState<number | null>(null)  // the document whose deletion is being confirmed
  const [busy, setBusy] = useState(false)  // a click is being answered: a second one would repeat it
  const load = useCallback(() => api.expired().then((r) => { setData(r); setError('') }).catch((e) => setError(errorText(e))), [])
  useEffect(() => { void load() }, [load])

  const remove = async (id: number, name: string) => {
    if (busy) return
    setBusy(true)
    setAsking(null)
    try {
      await api.deleteExpired(id)
      setNote({ ok: true, text: t('expired.deleted', { name }) })
    } catch (e) { setNote({ ok: false, text: msg(errorText(e)) }) }
    await load()
    setBusy(false)
  }

  if (!data) {
    return error
      ? <div role="alert" className="space-y-2"><p className="text-rose-700">{msg(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void load()}>{t('common.retry')}</Button></div>
      : <p className="text-slate-500">{t('common.loading')}</p>
  }
  return (
    <div className="space-y-3 text-sm">
      <p className="text-slate-600">{t('expired.hint')}</p>
      <Notice note={note} />
      <p role="alert" className="empty:hidden text-rose-700">{error && msg(error)}</p>
      {!data.configured && <p>{t('expired.notConfigured')}</p>}
      {data.configured && data.expired.length === 0 && <p className="text-slate-500">{t('expired.none')}</p>}
      <ul>
        {data.expired.map((d) => (
          <li key={d.id} className="border-b py-2 last:border-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0">
                <strong className="break-words">{d.name}</strong>
                <span className="block text-slate-600">{d.company} · {d.document_type}</span>
                <span className="block text-slate-600">{t('expired.row', { n: d.years, date: date(d.date), expired: date(d.expired_on) })}</span>
              </span>
              <span className="flex flex-wrap items-center gap-2">
                <a className="text-blue-700 underline" href={api.libraryFileUrl(d.path)} target="_blank" rel="noreferrer">{t('expired.open')}</a>
                <Button variant="outline" size="sm" disabled={busy} onClick={() => setAsking(d.id)}
                  aria-label={t('expired.deleteLabel', { name: d.name })}>{t('expired.delete')}</Button>
              </span>
            </div>
            {asking === d.id && (
              <div role="alertdialog" aria-label={t('expired.confirm', { name: d.name })}
                className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50 p-2">
                <p className="min-w-0 flex-1 break-words">{t('expired.confirm', { name: d.name })}</p>
                <Button size="sm" disabled={busy} onClick={() => void remove(d.id, d.name)}>{t('library.ok')}</Button>
                <Button size="sm" variant="outline" autoFocus onClick={() => setAsking(null)}>{t('library.cancel')}</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {data.total > data.expired.length && <p className="text-amber-700">{t('expired.more', { shown: data.expired.length, total: data.total })}</p>}
    </div>
  )
}
