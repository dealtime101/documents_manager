import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, errorText, type Operation } from '@/api'
import { Notice } from '@/components/Bits'
import { opLabel } from '@/ops'
import { baseName, dirName } from '@/paths'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'

/** From and To in ONE format: the file name, then its folder; the whole path stays in the tooltip. */
function PathCell({ path }: { path: string }) {
  return (
    <td className="max-w-80" title={path}>
      <div className="truncate">{baseName(path)}</div>
      <div className="truncate text-xs text-slate-500">{dirName(path)}</div>
    </td>
  )
}

export default function History() {
  const { t, msg, time } = useI18n()
  const [ops, setOps] = useState<Operation[] | null>(null)  // null: not loaded yet, which is not the same as empty
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)  // the result of the last undo
  // the raw server text, translated when shown (like undo's): so it is in the reader's language, and follows a language switch
  const [loadError, setLoadError] = useState('')
  const load = useCallback(() => api.history().then((rows) => { setOps(rows); setLoadError('') })
    .catch((e) => setLoadError(errorText(e))), [])
  useEffect(() => { load() }, [load])
  // the same object until note or loadError change: Notice treats a new object as a new message to announce
  // a failed reload is ALWAYS shown, after the result of the undo that came before it: the list is then stale and must say so
  const shownNote = useMemo(
    () => (loadError ? { ok: false, text: `${note?.ok ? `${note.text} ` : ''}${msg(loadError)}` } : note), [note, loadError, msg])
  // one undo at a time: a second click (or a double click) while one is running would ask for the same operation twice
  const [undoing, setUndoing] = useState<number | null>(null)

  const undo = async (id: number) => {
    if (undoing !== null || !confirm(t('hist.confirmUndo'))) return
    setUndoing(id)
    try {
      const r = await api.undo(id)
      setNote({ ok: true, text: t('hist.restored', { path: r.restored }) })
    } catch (e) {
      setNote({ ok: false, text: msg(errorText(e)) })
    }
    await load()
    setUndoing(null)
    // the button that was pressed is gone (replaced by "undone"): put the focus on its row, or it falls back to <body>
    requestAnimationFrame(() => document.getElementById(`op-${id}`)?.focus())
  }

  return (
    <div className="space-y-3">
      {/* live regions that are in the page BEFORE their text arrives, or the text is not announced */}
      <Notice note={shownNote} />
      <table className="w-full text-sm">
        <caption className="sr-only">{t('hist.caption')}</caption>
        <thead>
          <tr className="border-b text-left text-slate-500">
            <th scope="col" className="p-2">#</th><th scope="col">{t('field.date')}</th><th scope="col">{t('hist.op')}</th>
            <th scope="col">{t('hist.from')}</th><th scope="col">{t('hist.to')}</th>
            <th scope="col"><span className="sr-only">{t('hist.actions')}</span></th>
          </tr>
        </thead>
        <tbody>
          {(ops ?? []).map((o) => (
            <tr key={o.id} id={`op-${o.id}`} tabIndex={-1}  /* tabIndex -1: focus lands here after an undo, but the row is not a tab stop */
              className={`border-b outline-none focus-visible:bg-slate-50 ${o.undone ? 'text-slate-500 line-through' : ''}`}>
              <td className="p-2">{o.id}</td><td>{time(o.ts)}</td><td>{opLabel(t, o.kind)}</td>
              <PathCell path={o.src} />
              <PathCell path={o.dst} />
              <td>
                {o.undone
                  ? <span className="inline-block text-xs font-medium text-slate-600">{t('hist.undone')}</span>
                  : <Button size="sm" variant="outline" aria-disabled={undoing !== null} onClick={() => undo(o.id)}
                      className="aria-disabled:pointer-events-none aria-disabled:opacity-50"  /* aria-disabled, not disabled: keeps the focus */
                      aria-label={t('hist.undoOp', { id: o.id, file: baseName(o.src) })}>{t('hist.undo')}</Button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {ops === null && !loadError && <p role="status" className="text-slate-500">{t('common.loading')}</p>}
      {ops?.length === 0 && <p className="text-slate-500">{t('hist.none')}</p>}   {/* only after a load that succeeded */}
    </div>
  )
}
