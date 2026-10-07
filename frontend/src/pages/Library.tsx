import { useEffect, useState } from 'react'
import { api, errorText, type LibraryListing } from '@/api'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'

const join = (dir: string, name: string) => (dir ? `${dir}/${name}` : name)
const isPdf = (name: string) => name.toLowerCase().endsWith('.pdf')

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** A read-only explorer of the library: walk the folders, preview a PDF. It never moves, renames or deletes anything. */
export default function Library() {
  const { t, msg, lang } = useI18n()
  const [path, setPath] = useState('')
  const [reload, setReload] = useState(0)
  const [list, setList] = useState<LibraryListing | null>(null)
  const [error, setError] = useState('')
  const [file, setFile] = useState<string | null>(null)  // the selected file, relative to the library

  useEffect(() => {
    let current = true  // a slow answer for a folder already left must not replace the one shown
    api.library(path).then((l) => { if (current) { setList(l); setError('') } })
      .catch((e) => { if (current) { setList(null); setError(errorText(e)) } })
    return () => { current = false }
  }, [path, reload])

  const go = (to: string) => { setPath(to); setFile(null) }
  const crumbs = path ? path.split('/') : []

  return (
    <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-7rem)] lg:grid-cols-[24rem_minmax(0,1fr)]">
      <aside className="flex min-h-0 min-w-0 flex-col gap-2 overflow-hidden max-lg:max-h-96">
        <nav aria-label={t('library.path')} className="flex flex-wrap items-center gap-1 text-sm">
          <button type="button" className="text-blue-700 underline" onClick={() => go('')}>{t('library.root')}</button>
          {crumbs.map((name, i) => (
            <span key={i} className="flex items-center gap-1">
              <span aria-hidden="true">/</span>
              <button type="button" className="text-blue-700 underline" onClick={() => go(crumbs.slice(0, i + 1).join('/'))}>{name}</button>
            </span>
          ))}
        </nav>
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" disabled={!list || list.is_root} onClick={() => list && go(list.parent)}>{t('library.up')}</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => setReload((n) => n + 1)}>{t('library.refresh')}</Button>
        </div>
        {error && <p role="alert" className="text-sm text-rose-700"><span aria-hidden="true">✕ </span>{msg(error)}</p>}
        {list && (
          <div className="min-h-0 flex-1 overflow-y-auto rounded-md border">
            {list.folders.length === 0 && list.files.length === 0 && <p className="p-3 text-sm text-slate-600">{t('library.empty')}</p>}
            {list.folders.length > 0 && (
              <ul aria-label={t('library.folders')}>
                {list.folders.map((name) => (
                  <li key={name}>
                    <button type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-100" onClick={() => go(join(list.path, name))}>
                      <span aria-hidden="true">📁</span><span className="truncate">{name}</span>
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
                      <button type="button" aria-current={file === rel} onClick={() => setFile(rel)}
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
          </div>
        )}
      </aside>
      <section className="flex min-h-0 min-w-0 flex-col gap-2">
        {file ? (
          <>
            <div className="flex items-center justify-between gap-2">
              <h2 className="truncate text-lg font-semibold">{file.split('/').pop()}</h2>
              <a className="shrink-0 text-sm text-blue-700 underline" href={api.libraryFileUrl(file)} target="_blank" rel="noreferrer">
                {isPdf(file) ? t('library.open') : t('library.download')}
              </a>
            </div>
            {isPdf(file)
              ? <iframe title={t('library.preview')} src={api.libraryFileUrl(file)} className="h-[70vh] w-full flex-1 rounded-md border lg:h-full" />
              : <p className="text-sm text-slate-600">{t('library.noPreview')}</p>}
          </>
        ) : (
          <p className="text-sm text-slate-600">{t('library.pick')}</p>
        )}
      </section>
    </div>
  )
}
