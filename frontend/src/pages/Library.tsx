import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, errorText, type LibraryFields, type LibraryHit, type LibraryListing, type LibraryPlan } from '@/api'
import { Field, NameInput, Notice } from '@/components/Bits'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'

const TRASH = '_Trash'
const join = (dir: string, name: string) => (dir ? `${dir}/${name}` : name)
const dirOf = (path: string) => path.split('/').slice(0, -1).join('/')
const baseOf = (path: string) => path.split('/').pop() ?? path
const extOf = (path: string) => { const n = baseOf(path); const i = n.lastIndexOf('.'); return i > 0 ? n.slice(i) : '' }
const isPdf = (name: string) => name.toLowerCase().endsWith('.pdf')
const inTrash = (path: string) => path === TRASH || path.startsWith(`${TRASH}/`)
const EMPTY: LibraryFields = { company: '', document_type: '', date: 'XXXX', detail: '', amount: '', currency: 'CAD' }

/** A file size in the language of the page: "1,5 Mo" in French (o, Ko, Mo; decimal comma), "1.5 MB" in English. */
function size(bytes: number, t: (k: 'size.b' | 'size.kb' | 'size.mb') => string, lang: string): string {
  const number = (n: number, digits: number) => new Intl.NumberFormat(lang, { maximumFractionDigits: digits }).format(n)
  if (bytes < 1024) return `${number(bytes, 0)} ${t('size.b')}`
  if (bytes < 1024 * 1024) return `${number(bytes / 1024, 0)} ${t('size.kb')}`
  return `${number(bytes / 1024 / 1024, 1)} ${t('size.mb')}`
}

/** One line of text to type (a new name), shown where it is needed: the browser's own prompt() is not reliable in a desktop window. */
function AskName({ label, initial, ext = '', onOk, onCancel }: { label: string; initial: string; ext?: string; onOk: (v: string) => void; onCancel: () => void }) {
  const { t } = useI18n()
  const [v, setV] = useState(ext && initial.toLowerCase().endsWith(ext.toLowerCase()) ? initial.slice(0, -ext.length) : initial)  // a file's extension is fixed
  const submit = (e: FormEvent) => { e.preventDefault(); onOk(v.trim() + ext) }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 rounded-md border bg-slate-50 p-2">
      <div className="min-w-0 flex-1">
        <Field label={label}>
          <NameInput ext={ext} value={v + ext} onChange={(full) => setV(ext ? full.slice(0, -ext.length) : full)} />
        </Field>
      </div>
      <Button type="submit" size="sm" disabled={!v.trim()}>{t('library.ok')}</Button>
      <Button type="button" size="sm" variant="outline" onClick={onCancel}>{t('library.cancel')}</Button>
    </form>
  )
}

/** A question asked in the page itself, like AskName (the browser's own confirmation box is not reliable in a desktop window): the sentence and two buttons.
 *  The focus starts on Cancel: a stray Enter never deletes anything. */
function Confirm({ text, onOk, onCancel }: { text: string; onOk: () => void; onCancel: () => void }) {
  const { t } = useI18n()
  return (
    <div role="alertdialog" aria-label={text} className="flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-sm">
      <p className="min-w-0 flex-1 break-words">{text}</p>
      <Button type="button" size="sm" onClick={onOk}>{t('library.ok')}</Button>
      <Button type="button" size="sm" variant="outline" autoFocus onClick={onCancel}>{t('library.cancel')}</Button>
    </div>
  )
}

/** Where to move something: the library's folders, walked one level at a time. */
function MovePicker({ from, onPick, onCancel }: { from: string; onPick: (to: string) => void; onCancel: () => void }) {
  const { t, msg } = useI18n()
  const [at, setAt] = useState(dirOf(from))
  const [list, setList] = useState<LibraryListing | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    api.library(at).then((l) => { if (current) { setList(l); setError('') } }).catch((e) => { if (current) setError(errorText(e)) })
    return () => { current = false }
  }, [at])
  return (
    <div className="rounded-md border bg-slate-50 p-2 text-sm">
      <p className="mb-1 font-medium">{t('library.moveTo')} <span className="font-mono text-xs">/{at}</span></p>
      {error && <p role="alert" className="text-rose-700">{msg(error)}</p>}
      <div className="mb-1 flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" disabled={!at} onClick={() => setAt(dirOf(at))}>{t('library.up')}</Button>
        <Button type="button" size="sm" onClick={() => onPick(at)}>{t('library.moveHere')}</Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>{t('library.cancel')}</Button>
      </div>
      <ul className="max-h-40 overflow-auto">
        {/* the paths come from the folder the list was read FOR (list.path), not from `at`, which already names the next one while it loads */}
        {list?.folders.filter((f) => join(list.path, f) !== from && join(list.path, f) !== TRASH).map((f) => (
          <li key={f}><button type="button" className="w-full rounded px-1 py-0.5 text-left hover:bg-slate-200" onClick={() => setAt(join(list.path, f))}>📁 {f}</button></li>
        ))}
      </ul>
    </div>
  )
}

/** The right-hand form of a PDF: read the document for a proposal, correct it, and re-file it under its new name and folder. */
function Classify({ file, onFiled, setNote }: { file: string; onFiled: (path: string) => void; setNote: (n: { ok: boolean; text: string } | null) => void }) {
  const { t, msg } = useI18n()
  const [form, setForm] = useState<LibraryFields>(EMPTY)
  const [relDir, setRelDir] = useState('')
  const [finalName, setFinalName] = useState('')
  const [plan, setPlan] = useState<LibraryPlan | null>(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [touched, setTouched] = useState(false)  // the form holds something typed or proposed: the preview follows it
  const [vocab, setVocab] = useState<{ companies: string[]; types: string[] }>({ companies: [], types: [] })
  const [dirs, setDirs] = useState<string[]>([])

  useEffect(() => { api.vocabulary().then(setVocab).catch(() => {}); api.destinations().then(setDirs).catch(() => {}) }, [])
  const shown = useRef(file)  // the file the form is about NOW: a proposal read for another one arrives too late and is dropped
  const [planned, setPlanned] = useState('')  // the inputs the shown plan was computed FOR: an older preview is not offered for Apply
  useEffect(() => { shown.current = file; setForm(EMPTY); setRelDir(''); setFinalName(''); setPlan(null); setPlanned(''); setProblem(''); setTouched(false) }, [file])

  // the name and folder they give, recomputed shortly after each change
  useEffect(() => {
    if (!touched) return
    const asked = JSON.stringify([form, relDir, finalName])
    if (planned === asked) return  // the plan shown is already for these inputs (a proposal just brought it): no second request
    let current = true
    const timer = setTimeout(() => {
      api.libraryPlan(file, form, relDir, finalName)
        .then((p) => { if (current) { setPlan(p); setPlanned(asked); setProblem('') } })
        .catch((e) => { if (current) { setPlan(null); setPlanned(''); setProblem(errorText(e)) } })
    }, 400)
    return () => { current = false; clearTimeout(timer) }
  }, [file, form, relDir, finalName, touched, planned])

  const set = (k: keyof LibraryFields) => (e: { target: { value: string } }) => { setForm({ ...form, [k]: e.target.value }); setTouched(true) }
  const suggest = async () => {
    const asked = file
    setBusy(true)
    try {
      const p = await api.libraryPlan(asked)
      if (shown.current !== asked) return  // another file was selected while this one was read: its form is not this proposal's
      setForm(p.fields); setRelDir(''); setFinalName(''); setPlan(p); setPlanned(JSON.stringify([p.fields, '', ''])); setProblem(''); setTouched(true)
    } catch (e) { if (shown.current === asked) setProblem(errorText(e)) } finally { setBusy(false) }
  }
  const apply = async () => {
    setBusy(true)
    try {
      const r = await api.libraryApply(file, form, relDir, finalName)
      const learned = r.learned.map((l) => t(`learned.${l.kind}`, { v: l.value, c: l.company })).join('; ')
      setNote({ ok: true, text: t('library.filed', { path: r.path }) + (learned ? ` ${t('queue.learned', { list: learned })}` : '') })
      onFiled(r.path)
    } catch (e) { setProblem(errorText(e)) } finally { setBusy(false) }
  }
  const ready = !!plan?.final_name && !!plan?.rel_dir && planned === JSON.stringify([form, relDir, finalName])  // and it is for what is typed NOW

  return (
    <div className="min-h-0 min-w-0 space-y-3 overflow-y-auto pr-1">
      <datalist id="lib-companies">{vocab.companies.map((c) => <option key={c} value={c} />)}</datalist>
      <datalist id="lib-types">{vocab.types.map((c) => <option key={c} value={c} />)}</datalist>
      <datalist id="lib-dirs">{dirs.map((c) => <option key={c} value={c} />)}</datalist>
      <Button type="button" variant="outline" disabled={busy} aria-busy={busy} onClick={suggest}>{busy ? t('library.reading') : t('library.suggest')}</Button>
      <fieldset disabled={busy} className="min-w-0 space-y-3 border-0 p-0">
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('field.company')}><Input list="lib-companies" value={form.company} onChange={set('company')} /></Field>
          <Field label={t('field.type')}><Input list="lib-types" value={form.document_type} onChange={set('document_type')} /></Field>
          <Field label={t('field.dateFull')}><Input value={form.date} onChange={set('date')} /></Field>
          <Field label={t('field.detail')}><Input value={form.detail} onChange={set('detail')} /></Field>
          <Field label={t('field.amount')}><Input inputMode="decimal" value={form.amount} onChange={set('amount')} /></Field>
          <Field label={t('field.currency')}><Input value={form.currency} maxLength={3} onChange={set('currency')} /></Field>
        </div>
        <Field label={t('field.folder')}>
          <Input list="lib-dirs" value={relDir} placeholder={plan?.rel_dir ?? ''} onChange={(e) => { setRelDir(e.target.value); setTouched(true) }} />
        </Field>
        <Field label={t('field.fileName')}>
          <NameInput value={finalName} placeholder={plan?.final_name ?? ''} onChange={(v) => { setFinalName(v); setTouched(true) }} />
        </Field>
      </fieldset>
      {problem && <p role="alert" className="text-sm text-rose-700"><span aria-hidden="true">✕ </span>{msg(problem)}</p>}
      {plan && ready && <p className="break-all text-sm text-slate-700">{t('library.willBe')} <span className="font-mono">{plan.rel_dir}/{plan.final_name}</span></p>}
      <Button type="button" disabled={busy || !ready} onClick={apply}>{t('library.apply')}</Button>
    </div>
  )
}

/** The library: walk the folders, find by name, preview, rename / move / delete, create folders, and re-file a PDF from its fields.
 *  Deleting puts in a `_Trash` folder; only what is already there is removed for good. Nothing is ever replaced. */
export default function Library() {
  const { t, msg, lang } = useI18n()
  const [path, setPath] = useState('')
  const [reload, setReload] = useState(0)
  const [list, setList] = useState<LibraryListing | null>(null)
  const [error, setError] = useState('')
  const [file, setFile] = useState<string | null>(null)  // the selected file, relative to the library
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<{ hits: LibraryHit[]; truncated: boolean } | null>(null)
  const [ask, setAsk] = useState<'newFolder' | 'renameFolder' | 'renameFile' | null>(null)
  const [moving, setMoving] = useState<'folder' | 'file' | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)  // the folder or file whose deletion is being confirmed
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let current = true  // a slow answer for a folder already left must not replace the one shown
    api.library(path).then((l) => { if (current) { setList(l); setError('') } })
      .catch((e) => { if (current) { setList(null); setError(errorText(e)) } })
    return () => { current = false }
  }, [path, reload])

  const refresh = () => setReload((n) => n + 1)
  const go = (to: string, select: string | null = null) => { setPath(to); setFile(select); setAsk(null); setMoving(null); setConfirming(null); setFound(null); setQuery('') }
  const sentence = (target: string) => t(inTrash(target) ? 'library.confirmForever' : 'library.confirmTrash', { name: baseOf(target) })
  const crumbs = path ? path.split('/') : []

  /** Runs one change, says what happened, and shows the folder again. */
  const act = async (run: () => Promise<string>) => {
    setBusy(true)
    try { setNote({ ok: true, text: await run() }); setAsk(null); setMoving(null); refresh() }
    catch (e) { setNote({ ok: false, text: msg(errorText(e)) }) }
    finally { setBusy(false) }
  }
  const remove = (target: string) => {
    setConfirming(null)
    const forever = inTrash(target)
    void act(async () => {
      await api.libraryDelete(target)
      if (file && (file === target || file.startsWith(`${target}/`))) setFile(null)
      if (path === target) setPath(dirOf(target))
      return t(forever ? 'library.deletedForever' : 'library.trashed', { name: baseOf(target) })
    })
  }

  const search = async (e: FormEvent) => {
    e.preventDefault()
    if (query.trim().length < 2) return
    setBusy(true)
    try { setFound(await api.librarySearch(query.trim())); setNote(null) } catch (err) { setNote({ ok: false, text: msg(errorText(err)) }) } finally { setBusy(false) }
  }

  const folderActions = path && path !== TRASH
  return (
    <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-7rem)] lg:grid-cols-[24rem_minmax(0,1fr)]">
      <aside className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden max-lg:max-h-[28rem]">
        <form onSubmit={search} className="flex gap-2" role="search">
          <Input aria-label={t('library.search')} placeholder={t('library.search')} value={query} onChange={(e) => { setQuery(e.target.value); if (!e.target.value) setFound(null) }} />
          <Button type="submit" size="sm" disabled={busy || query.trim().length < 2}>{t('library.find')}</Button>
        </form>
        <nav aria-label={t('library.path')} className="flex flex-wrap items-center gap-1 text-sm">
          <button type="button" className="text-blue-700 underline" onClick={() => go('')}>{t('library.root')}</button>
          {crumbs.map((name, i) => (
            <span key={i} className="flex items-center gap-1">
              <span aria-hidden="true">/</span>
              <button type="button" className="text-blue-700 underline" onClick={() => go(crumbs.slice(0, i + 1).join('/'))}>{name}</button>
            </span>
          ))}
        </nav>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" disabled={!list || list.is_root} onClick={() => list && go(list.parent)}>{t('library.up')}</Button>
          <Button type="button" variant="outline" size="sm" onClick={refresh}>{t('library.refresh')}</Button>
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setAsk('newFolder')}>{t('library.newFolder')}</Button>
          {folderActions && (
            <>
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setAsk('renameFolder')}>{t('library.renameFolder')}</Button>
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setMoving('folder')}>{t('library.moveFolder')}</Button>
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setConfirming(path)}>{t(inTrash(path) ? 'library.deleteForever' : 'library.deleteFolder')}</Button>
            </>
          )}
        </div>
        {ask === 'newFolder' && <AskName label={t('library.newFolderName')} initial="" onCancel={() => setAsk(null)}
          onOk={(v) => void act(async () => { const r = await api.libraryNewFolder(path, v); go(r.path); return t('library.created', { name: v }) })} />}
        {ask === 'renameFolder' && <AskName label={t('library.newName')} initial={baseOf(path)} onCancel={() => setAsk(null)}
          onOk={(v) => void act(async () => { const r = await api.libraryRename(path, v); go(r.path); return t('library.renamed', { name: v }) })} />}
        {moving === 'folder' && <MovePicker from={path} onCancel={() => setMoving(null)}
          onPick={(to) => void act(async () => { const r = await api.libraryMove(path, to); go(r.path); return t('library.moved', { path: r.path }) })} />}
        {confirming !== null && confirming === path && <Confirm text={sentence(path)} onCancel={() => setConfirming(null)} onOk={() => remove(path)} />}
        {error && <p role="alert" className="text-sm text-rose-700"><span aria-hidden="true">✕ </span>{msg(error)}</p>}
        <div className="min-h-0 flex-1 overflow-y-auto rounded-md border">
          {found ? (
            <>
              {found.hits.length === 0 && <p className="p-3 text-sm text-slate-600">{t('library.noResult')}</p>}
              <ul aria-label={t('library.results')}>
                {found.hits.map((h) => (
                  <li key={h.path}>
                    <button type="button" className="block w-full px-3 py-1.5 text-left hover:bg-slate-100"
                      onClick={() => (h.is_dir ? go(h.path) : go(h.folder, h.path))}>
                      <span aria-hidden="true">{h.is_dir ? '📁' : isPdf(h.name) ? '📄' : '📎'} </span>{h.name}
                      <span className="block truncate text-xs text-slate-600">/{h.folder}</span>
                    </button>
                  </li>
                ))}
              </ul>
              {found.truncated && <p className="p-3 text-sm text-amber-700">{t('library.truncatedSearch')}</p>}
            </>
          ) : list && (
            <>
              {list.folders.length === 0 && list.files.length === 0 && <p className="p-3 text-sm text-slate-600">{t('library.empty')}</p>}
              {list.folders.length > 0 && (
                <ul aria-label={t('library.folders')}>
                  {list.folders.map((name) => (
                    <li key={name}>
                      <button type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-100" onClick={() => go(join(list.path, name))}>
                        <span aria-hidden="true">{name === TRASH && !list.path ? '🗑' : '📁'}</span><span className="truncate">{name}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {list.files.length > 0 && (
                <ul aria-label={t('library.files')}>
                  {list.files.map((f) => {
                    const rel = join(list.path, f.name)
                    return (
                      <li key={f.name}>
                        <button type="button" aria-current={file === rel} onClick={() => { setFile(rel); setAsk(null); setMoving(null) }}
                          className={`flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-100 ${file === rel ? 'bg-slate-200' : ''}`}>
                          <span aria-hidden="true">{isPdf(f.name) ? '📄' : '📎'}</span>
                          <span className="min-w-0 flex-1 truncate">{f.name}</span>
                          <span className="shrink-0 text-xs text-slate-600">{size(f.size, t, lang)} ·{new Date(f.modified * 1000).toLocaleDateString(lang)}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
              {list.truncated && <p className="p-3 text-sm text-amber-700">{t('library.truncated')}</p>}
            </>
          )}
        </div>
      </aside>
      <section className="flex min-h-0 min-w-0 flex-col gap-2">
        <Notice note={note} />
        {file ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="min-w-0 truncate text-lg font-semibold">{baseOf(file)}</h2>
              <div className="flex flex-wrap items-center gap-2">
                <a className="text-sm text-blue-700 underline" href={api.libraryFileUrl(file)} target="_blank" rel="noreferrer">
                  {isPdf(file) ? t('library.open') : t('library.download')}
                </a>
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setAsk('renameFile')}>{t('library.rename')}</Button>
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setMoving('file')}>{t('library.move')}</Button>
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setConfirming(file)}>{t(inTrash(file) ? 'library.deleteForever' : 'library.delete')}</Button>
              </div>
            </div>
            {ask === 'renameFile' && <AskName label={t('library.newName')} initial={baseOf(file)} ext={extOf(file)} onCancel={() => setAsk(null)}
              onOk={(v) => void act(async () => { const r = await api.libraryRename(file, v); setFile(r.path); return t('library.renamed', { name: v }) })} />}
            {confirming !== null && confirming === file && <Confirm text={sentence(file)} onCancel={() => setConfirming(null)} onOk={() => remove(file)} />}
            {moving === 'file' && <MovePicker from={file} onCancel={() => setMoving(null)}
              onPick={(to) => void act(async () => { const r = await api.libraryMove(file, to); go(dirOf(r.path), r.path); return t('library.moved', { path: r.path }) })} />}
            {isPdf(file) ? (
              <div className="grid min-h-0 min-w-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-2">
                <iframe title={t('library.preview')} src={api.libraryFileUrl(file)} className="h-[70vh] w-full rounded-md border xl:h-full" />
                <Classify file={file} setNote={setNote} onFiled={(p) => { go(dirOf(p), p) }} />
              </div>
            ) : <p className="text-sm text-slate-600">{t('library.noPreview')}</p>}
          </>
        ) : (
          <p className="text-sm text-slate-600">{t('library.pick')}</p>
        )}
      </section>
    </div>
  )
}
