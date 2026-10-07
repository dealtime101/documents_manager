import { useEffect, useState, type FormEvent } from 'react'
import { api, errorText, type LibraryFields, type LibraryHit, type LibraryListing, type LibraryPlan } from '@/api'
import { Field, Notice } from '@/components/Bits'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'

const TRASH = '_Trash'
const join = (dir: string, name: string) => (dir ? `${dir}/${name}` : name)
const dirOf = (path: string) => path.split('/').slice(0, -1).join('/')
const baseOf = (path: string) => path.split('/').pop() ?? path
const isPdf = (name: string) => name.toLowerCase().endsWith('.pdf')
const inTrash = (path: string) => path === TRASH || path.startsWith(`${TRASH}/`)
const EMPTY: LibraryFields = { company: '', document_type: '', date: 'XXXX', detail: '', amount: '', currency: 'CAD' }

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** One line of text to type (a new name), shown where it is needed: the browser's own prompt() is not reliable in a desktop window. */
function AskName({ label, initial, onOk, onCancel }: { label: string; initial: string; onOk: (v: string) => void; onCancel: () => void }) {
  const { t } = useI18n()
  const [v, setV] = useState(initial)
  const submit = (e: FormEvent) => { e.preventDefault(); onOk(v.trim()) }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 rounded-md border bg-slate-50 p-2">
      <div className="min-w-0 flex-1"><Field label={label}><Input autoFocus value={v} onChange={(e) => setV(e.target.value)} /></Field></div>
      <Button type="submit" size="sm" disabled={!v.trim()}>{t('library.ok')}</Button>
      <Button type="button" size="sm" variant="outline" onClick={onCancel}>{t('library.cancel')}</Button>
    </form>
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
        {list?.folders.filter((f) => join(at, f) !== from && join(at, f) !== TRASH).map((f) => (
          <li key={f}><button type="button" className="w-full rounded px-1 py-0.5 text-left hover:bg-slate-200" onClick={() => setAt(join(at, f))}>📁 {f}</button></li>
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
  useEffect(() => { setForm(EMPTY); setRelDir(''); setFinalName(''); setPlan(null); setProblem(''); setTouched(false) }, [file])

  // the name and folder they give, recomputed shortly after each change
  useEffect(() => {
    if (!touched) return
    let current = true
    const timer = setTimeout(() => {
      api.libraryPlan(file, form, relDir, finalName)
        .then((p) => { if (current) { setPlan(p); setProblem('') } })
        .catch((e) => { if (current) { setPlan(null); setProblem(errorText(e)) } })
    }, 400)
    return () => { current = false; clearTimeout(timer) }
  }, [file, form, relDir, finalName, touched])

  const set = (k: keyof LibraryFields) => (e: { target: { value: string } }) => { setForm({ ...form, [k]: e.target.value }); setTouched(true) }
  const suggest = async () => {
    setBusy(true)
    try {
      const p = await api.libraryPlan(file)
      setForm(p.fields); setRelDir(''); setFinalName(''); setPlan(p); setProblem(''); setTouched(true)
    } catch (e) { setProblem(errorText(e)) } finally { setBusy(false) }
  }
  const apply = async () => {
    setBusy(true)
    try {
      const r = await api.libraryApply(file, form, relDir, finalName)
      setNote({ ok: true, text: t('library.filed', { path: r.path }) })
      onFiled(r.path)
    } catch (e) { setProblem(errorText(e)) } finally { setBusy(false) }
  }
  const ready = !!plan?.final_name && !!plan?.rel_dir

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
          <Input value={finalName} placeholder={plan?.final_name ?? ''} onChange={(e) => { setFinalName(e.target.value); setTouched(true) }} />
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
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let current = true  // a slow answer for a folder already left must not replace the one shown
    api.library(path).then((l) => { if (current) { setList(l); setError('') } })
      .catch((e) => { if (current) { setList(null); setError(errorText(e)) } })
    return () => { current = false }
  }, [path, reload])

  const refresh = () => setReload((n) => n + 1)
  const go = (to: string, select: string | null = null) => { setPath(to); setFile(select); setAsk(null); setMoving(null); setFound(null); setQuery('') }
  const crumbs = path ? path.split('/') : []

  /** Runs one change, says what happened, and shows the folder again. */
  const act = async (run: () => Promise<string>) => {
    setBusy(true)
    try { setNote({ ok: true, text: await run() }); setAsk(null); setMoving(null); refresh() }
    catch (e) { setNote({ ok: false, text: msg(errorText(e)) }) }
    finally { setBusy(false) }
  }
  const remove = (target: string) => {
    const forever = inTrash(target)
    if (!confirm(t(forever ? 'library.confirmForever' : 'library.confirmTrash', { name: baseOf(target) }))) return
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
          <Button type="button" variant="outline" size="sm" onClick={() => setAsk('newFolder')}>{t('library.newFolder')}</Button>
          {folderActions && (
            <>
              <Button type="button" variant="outline" size="sm" onClick={() => setAsk('renameFolder')}>{t('library.renameFolder')}</Button>
              <Button type="button" variant="outline" size="sm" onClick={() => setMoving('folder')}>{t('library.moveFolder')}</Button>
              <Button type="button" variant="outline" size="sm" onClick={() => remove(path)}>{t(inTrash(path) ? 'library.deleteForever' : 'library.deleteFolder')}</Button>
            </>
          )}
        </div>
        {ask === 'newFolder' && <AskName label={t('library.newFolderName')} initial="" onCancel={() => setAsk(null)}
          onOk={(v) => void act(async () => { const r = await api.libraryNewFolder(path, v); go(r.path); return t('library.created', { name: v }) })} />}
        {ask === 'renameFolder' && <AskName label={t('library.newName')} initial={baseOf(path)} onCancel={() => setAsk(null)}
          onOk={(v) => void act(async () => { const r = await api.libraryRename(path, v); go(r.path); return t('library.renamed', { name: v }) })} />}
        {moving === 'folder' && <MovePicker from={path} onCancel={() => setMoving(null)}
          onPick={(to) => void act(async () => { const r = await api.libraryMove(path, to); go(r.path); return t('library.moved', { path: r.path }) })} />}
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
                          <span className="shrink-0 text-xs text-slate-600">{size(f.size)} · {new Date(f.modified * 1000).toLocaleDateString(lang)}</span>
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
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => remove(file)}>{t(inTrash(file) ? 'library.deleteForever' : 'library.delete')}</Button>
              </div>
            </div>
            {ask === 'renameFile' && <AskName label={t('library.newName')} initial={baseOf(file)} onCancel={() => setAsk(null)}
              onOk={(v) => void act(async () => { const r = await api.libraryRename(file, v); setFile(r.path); return t('library.renamed', { name: v }) })} />}
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
