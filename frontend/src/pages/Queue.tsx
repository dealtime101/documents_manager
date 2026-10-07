import { useCallback, useEffect, useRef, useState } from 'react'
import { api, DEFAULT_THRESHOLDS, errorText, type Batch, type Group, type Item, type Learned, type ScanJob, type Thresholds } from '@/api'
import { Confidence, Field, Notice, StatusBadge } from '@/components/Bits'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n, type AskKey } from '@/i18n'

type Form = {
  company: string; document_type: string; date: string; detail: string
  amount: string; currency: string; rel_dir: string; final_name: string
}

const toForm = (i: Item): Form => ({
  company: i.company ?? '', document_type: i.document_type ?? '', date: i.date, detail: i.detail,
  amount: i.amount ?? '', currency: i.currency, rel_dir: i.rel_dir, final_name: i.final_name,
})

// a tick-box approval files an item as the engine proposes it: only those that have a name and a destination (auto, confirm)
const approvable = (i: Item) => (i.status === 'auto' || i.status === 'confirm') && !!i.final_name && !!i.rel_dir

const GROUP_LABEL: Record<Group, AskKey> = {  // the same names as the dashboard tiles
  auto: 'dash.ready', needs_validation: 'dash.needsValidation', duplicates: 'dash.duplicates', errors: 'dash.errors',
}

export default function Queue({ group, onShowAll }: { group: Group | null; onShowAll: () => void }) {
  const { t, msg, percent } = useI18n()
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [sel, setSel] = useState<number | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [vocab, setVocab] = useState<{ companies: string[]; types: string[] }>({ companies: [], types: [] })
  const [dirs, setDirs] = useState<string[]>([])
  const [thresholds, setThresholds] = useState<Thresholds>(DEFAULT_THRESHOLDS)  // the engine's cut-offs, for the score colours
  const [job, setJob] = useState<ScanJob | null>(null)
  const [ticked, setTicked] = useState<ReadonlySet<number>>(new Set())  // the tick-boxes of the list: what a batch approval files
  const [minConf, setMinConf] = useState('85')

  const itemsRef = useRef(items)  // the list as shown, for load() to find the open document again
  itemsRef.current = items
  const current = items.find((i) => i.id === sel) ?? null
  // Kept in a ref so effects can report errors without being re-run when the language changes.
  const fail = useRef((e: unknown) => setNote({ ok: false, text: errorText(e) }))
  fail.current = (e: unknown) => setNote({ ok: false, text: msg(errorText(e)) })

  // `stay`: a new filter, not a save: the open document and what was typed in it survive when it is still in the new list
  const load = useCallback(async (keep?: number | null, stay = false) => {
    const { rows: fetched, total: all } = await api.items('pending', group ?? undefined)
    // A document being edited that the new filter does not contain stays in the list, on top, with what was typed in it: the
    // filter is already in the URL, so it cannot be refused, but nothing typed is thrown away.
    const edited = stay && dirtyRef.current && keep != null && !fetched.some((i) => i.id === keep)
      ? itemsRef.current.find((i) => i.id === keep) : undefined
    const list = edited ? [edited, ...fetched] : fetched
    setItems(list)
    setTotal(all)
    setTicked((t) => new Set(list.filter((i) => t.has(i.id) && approvable(i)).map((i) => i.id)))  // gone, or no longer approvable: forgotten
    const next = list.find((i) => i.id === keep) ?? list[0] ?? null
    setSel(next?.id ?? null)
    if (edited) setNote({ ok: true, text: tRef.current('queue.keptOutside') })
    if (stay && dirtyRef.current && next?.id === keep) return
    setForm(next ? toForm(next) : null)
  }, [group])  // not [t]: a language switch must not reload the list

  useEffect(() => {
    load(selRef.current, true).catch((e) => fail.current(e))
    api.vocabulary().then(setVocab).catch(() => {})
    api.thresholds().then(setThresholds).catch(() => {})  // failure: the shipped values stay (colours only, the status is the server's)
    api.destinations().then(setDirs).catch(() => {})
    api.scanStatus().then((j) => j.state === 'running' && setJob(j)).catch(() => {})
  }, [load])

  // The scan runs in the background (slow OCR): follow its progress and refresh the list as items arrive.
  const selRef = useRef(sel)
  selRef.current = sel
  const dirtyRef = useRef(false)  // the form holds an edit: the polled refresh must not replace it
  const tRef = useRef(t)
  tRef.current = t
  const groupRef = useRef(group)
  groupRef.current = group
  useEffect(() => {
    if (job?.state !== 'running') return
    let cancelled = false   // set when the effect is cleaned up: a late answer must not touch the state any more
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const j = await api.scanStatus()
        if (cancelled) return
        const { rows: list, total: all } = await api.items('pending', groupRef.current ?? undefined)
        if (cancelled) return
        setJob(j)
        setItems(list)  // the list only: never reset a form the user is typing in
        setTotal(all)
        setTicked((t) => new Set(list.filter((i) => t.has(i.id) && approvable(i)).map((i) => i.id)))  // as load() does
        // nothing selected, or the selected item left the list (filed elsewhere): show the first one, unless the form was edited
        if ((selRef.current === null || !list.some((i) => i.id === selRef.current)) && list[0] && !dirtyRef.current) {
          setSel(list[0].id); setForm(toForm(list[0]))
        }
        if (j.state === 'error') setNote({ ok: false, text: tRef.current('queue.scanFailed', { err: j.error }) })
        if (j.state === 'done') setNote({ ok: true, text: tRef.current('queue.scanDone', { n: j.created }) })
      } catch (e) {
        if (!cancelled) fail.current(e)
      }
      if (!cancelled) timer = setTimeout(tick, 3000)  // the next cycle starts only when this one is over: never two at once
    }
    timer = setTimeout(tick, 3000)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [job?.state])

  const run = async (fn: () => Promise<string>, keep?: number | null) => {
    setBusy(true)
    try {
      const text = await fn()
      if (text) setNote({ ok: true, text })
      await load(keep)
    } catch (e) {
      fail.current(e)
    } finally {
      setBusy(false)
    }
  }

  const changed = (item: Item, values: Form) => JSON.stringify(values) !== JSON.stringify(toForm(item))  // edited since loaded?
  const dirty = current && form && changed(current, form)
  dirtyRef.current = !!dirty
  const payload = (f: Form) => {
    // the name is only sent if it was edited by hand; otherwise the server recomputes it
    const { final_name, ...rest } = f
    return final_name !== current?.final_name ? { ...rest, final_name } : rest
  }
  const select = (i: Item) => {
    if (i.id === sel) return
    if (dirty && !confirm(t('queue.confirmDiscard'))) return  // never silently drop what was typed
    setSel(i.id); setForm(toForm(i)); setNote(null)
  }
  const describe = (l: Learned) => t(`learned.${l.kind}`, { v: l.value, c: l.company })

  const startScan = async () => {
    try { setJob((await api.scan()).job); setNote(null) } catch (e) { fail.current(e) }
  }
  // takes what it saves as arguments: the button only exists once there is a selected item AND its form, no assertion needed
  const save = (item: Item, values: Form) => run(async () => { await api.save(item.id, payload(values)); return t('queue.saved') }, item.id)
  const approve = (item: Item, values: Form) => run(async () => {  // item and form as arguments, like save(): nothing to assert
    if (changed(item, values)) await api.save(item.id, payload(values))
    const r = await api.approve(item.id)
    // the server's answer decides: an item can turn into a duplicate between the scan and the click
    if (r.item.status === 'duplicate') return t('queue.quarantined')
    const sentences = [t('queue.filed')]  // each message is a complete sentence: they are joined by a space
    if (r.learned.length) sentences.push(t('queue.learned', { list: r.learned.map(describe).join('; ') }))
    if (r.learning_failed) sentences.push(t('queue.learningFailed'))
    return sentences.join(' ')
  })
  const summary = (r: Batch) => {  // one message for both bulk approvals
    const name = (id: number) => items.find((i) => i.id === id)?.filename ?? `#${id}`
    let text = t('queue.approvedMany', { n: r.approved.length })  // each message is a COMPLETE sentence, punctuation included
    if (r.failed.length) {
      const list = r.failed.map((f) => `${name(f.id)} (${msg(f.detail)})`).join('; ')  // the same separator as the list of what was learned, in both languages
      text += ` ${t('queue.failedMany', { n: r.failed.length, list })}`
    }
    if (r.remaining) text += ` ${t('queue.moreToApprove', { n: r.remaining })}`  // one request files at most MAX_BATCH: press again
    return text
  }
  // a bulk action reloads the list and rebuilds the form from the server: like select(), never drop a typed edit unasked
  const keepEdit = () => !dirty || confirm(t('queue.confirmDiscard'))
  const approveAuto = () => {
    if (!keepEdit()) return
    return run(async () => summary(await api.approveAuto()), sel)  // sel: the current item stays if it is still in the list
  }
  const approveSelected = () => {
    if (!confirm(t('queue.confirmBatch', { n: ticks.length })) || !keepEdit()) return  // declined: nothing reloads, the selection and the form stay
    return run(async () => {
      const r = await api.approveSelected(ticks.map((i) => i.id))
      setTicked(new Set())
      return summary(r)
    }, sel)
  }
  const autoCount = items.filter((i) => i.status === 'auto').length
  const ticks = items.filter((i) => ticked.has(i.id) && approvable(i))  // the polled list also changes under the selection
  const tick = (ids: number[]) => setTicked((t) => new Set([...t, ...ids]))
  const toggle = (id: number) => setTicked((t) => { const n = new Set(t); if (!n.delete(id)) n.add(id); return n })
  // an emptied or out-of-range field must select NOTHING: Number('') is 0 and would tick every approvable item
  const minValid = minConf.trim() !== '' && Number.isFinite(Number(minConf)) && Number(minConf) >= 0 && Number(minConf) <= 100
  const selectFrom = () => minValid && tick(items.filter((i) => approvable(i) && i.confidence * 100 >= Number(minConf)).map((i) => i.id))
  const selectSame = (item: Item) => tick(items.filter((i) => approvable(i) && i.company === item.company
    && i.document_type === item.document_type).map((i) => i.id))
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value  // read now: the updater below runs later
    setForm((f) => (f ? { ...f, [k]: value } : f))  // from the latest state, and nothing to assert: no form, nothing to edit
  }

  return (
    // One column on narrow screens (list, then the document); the two-pane layout from the `lg` breakpoint up.
    // min-w-0 lets the panels shrink instead of overflowing the page.
    <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-7rem)] lg:grid-cols-[22rem_minmax(0,1fr)]">
      <aside className="flex min-w-0 flex-col gap-2 overflow-hidden max-lg:max-h-72">
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy || job?.state === 'running'} onClick={startScan}>
            {job?.state === 'running' ? t('queue.scanning', { done: job.done, total: job.total }) : t('queue.scan')}
          </Button>
          <Button variant="outline" disabled={busy || !autoCount} onClick={approveAuto}>
            {t('queue.approveAuto', { n: autoCount })}
          </Button>
        </div>
        {job?.state === 'running' && job.total > 0 && (
          <progress className="h-2 w-full" max={job.total} value={job.done} aria-label={t('queue.scanning', { done: job.done, total: job.total })} />
        )}
        <div className="flex flex-wrap items-end gap-2 text-xs">
          <label className="flex flex-col gap-0.5">{t('queue.minConfidence')}
            <Input type="number" min={0} max={100} step={5} value={minConf} className="h-7 w-20"
              onChange={(e) => setMinConf(e.target.value)} />
          </label>
          <Button variant="outline" size="sm" disabled={busy || !items.length || !minValid} onClick={selectFrom}>{t('queue.selectFrom')}</Button>
          <Button variant="outline" size="sm" disabled={busy || !current?.company || !current.document_type}
            onClick={() => current && selectSame(current)}>{t('queue.selectSame')}</Button>
        </div>
        <div className="flex gap-2">
          <Button size="sm" disabled={busy || !ticks.length} onClick={approveSelected}>
            {t('queue.approveSelected', { n: ticks.length })}
          </Button>
          <Button variant="outline" size="sm" disabled={busy || !ticks.length} onClick={() => setTicked(new Set())}>
            {t('queue.clearSelection')}
          </Button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto pr-1">
          {group && (
            <div className="flex items-center justify-between gap-2 rounded bg-slate-100 p-2 text-xs">
              <span>{t('queue.filtered', { group: t(GROUP_LABEL[group]) })}</span>
              <button type="button" className="font-medium underline" onClick={onShowAll}>{t('queue.showAll')}</button>
            </div>
          )}
          {items.length === 0 && <p className="p-4 text-sm text-slate-500">{t(group ? 'queue.emptyGroup' : 'queue.empty')}</p>}
          {total > items.length && (
            <p className="rounded bg-amber-50 p-2 text-xs text-amber-900">{t('queue.truncated', { shown: items.length, total })}</p>
          )}
          {items.map((i) => (
            <div key={i.id} className="flex items-start gap-2">
              <input type="checkbox" className="mt-3 size-4 shrink-0" checked={ticked.has(i.id)} disabled={busy || !approvable(i)}
                aria-label={t('queue.tick', { name: i.filename })} onChange={() => toggle(i.id)} />
              <button type="button" onClick={() => select(i)} disabled={busy}
                aria-current={i.id === sel ? 'true' : undefined}
                className={`min-w-0 flex-1 rounded-md border p-2 text-left text-sm ${i.id === sel ? 'border-slate-900 bg-slate-50' : 'hover:bg-slate-50'}`}>
                <div className="flex items-center justify-between gap-2">
                  <StatusBadge status={i.status} /><span className="text-xs text-slate-500">{percent(i.confidence)}</span>
                </div>
                <div className="mt-1 truncate font-medium">{i.filename}</div>
                <div className="truncate text-xs text-slate-500">{i.final_name || t('queue.nameToEnter')}</div>
              </button>
            </div>
          ))}
        </div>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-col gap-3">
      {/* ONE live region for every result (scan done, filed, error...), never unmounted: text added to a region that is
          already in the page is announced, a region created together with its text is not */}
      <Notice note={note} />
      {current && form ? (
        <section className="grid min-h-0 min-w-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-2">
          <iframe title={t('queue.preview')} src={api.pdfUrl(current.id)}
            className="h-[70vh] w-full rounded-md border xl:h-full" />
          <div className="min-h-0 min-w-0 space-y-3 overflow-y-auto pr-1">
            <div className="flex items-center justify-between">
              <h2 className="truncate text-lg font-semibold">{current.filename}</h2>
              <a className="text-sm text-blue-700 underline" href={api.pdfUrl(current.id)} target="_blank" rel="noreferrer">{t('queue.open')}</a>
            </div>
            <Confidence item={current} thresholds={thresholds} />
            {current.notes.map((n) => <p key={n} className="rounded bg-amber-50 p-2 text-sm text-amber-900">⚠ {msg(n)}</p>)}

            <datalist id="companies">{vocab.companies.map((c) => <option key={c} value={c} />)}</datalist>
            <datalist id="types">{vocab.types.map((c) => <option key={c} value={c} />)}</datalist>
            <datalist id="dirs">{dirs.map((c) => <option key={c} value={c} />)}</datalist>

            {/* locked while an action runs: what is typed meanwhile would be overwritten by the final reload */}
            <fieldset disabled={busy} className="min-w-0 space-y-3 border-0 p-0">
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('field.company')}><Input list="companies" value={form.company} onChange={set('company')} /></Field>
              <Field label={t('field.type')}><Input list="types" value={form.document_type} onChange={set('document_type')} /></Field>
              <Field label={t('field.dateFull')}><Input value={form.date} onChange={set('date')} /></Field>
              <Field label={t('field.detail')}><Input value={form.detail} onChange={set('detail')} /></Field>
              <Field label={t('field.amount')}><Input inputMode="decimal" value={form.amount} onChange={set('amount')} /></Field>
              <Field label={t('field.currency')}><Input value={form.currency} maxLength={3} onChange={set('currency')} /></Field>
            </div>
            <Field label={t('field.folder')}><Input list="dirs" value={form.rel_dir} onChange={set('rel_dir')} /></Field>
            <Field label={t('field.fileName')}><Input value={form.final_name} onChange={set('final_name')} /></Field>
            </fieldset>

            <div className="flex flex-wrap gap-2 pt-1">
              <Button disabled={busy} onClick={() => approve(current, form)}>{current.status === 'duplicate' ? t('queue.quarantine') : t('queue.approve')}</Button>
              <Button variant="outline" disabled={busy || !dirty} onClick={() => save(current, form)}>{t('queue.save')}</Button>
              <Button variant="outline" disabled={busy} onClick={() => run(async () => { await api.ignore(current.id); return t('queue.ignored') })}>{t('queue.ignore')}</Button>
              <Button variant="outline" disabled={busy} onClick={() => confirm(t('queue.confirmRemove')) && run(async () => { await api.remove(current.id); return t('queue.removed') })}>{t('queue.remove')}</Button>
            </div>
          </div>
        </section>
      ) : (
        <section className="grid flex-1 place-items-center text-slate-500">
          {!note && <p>{t('queue.noSelection')}</p>}
        </section>
      )}
      </div>
    </div>
  )
}
