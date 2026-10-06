import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText, type Dashboard as D, type Group } from '@/api'
import Accuracy from '@/components/Accuracy'
import { opLabel } from '@/ops'
import { baseName } from '@/paths'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useI18n, type AskKey } from '@/i18n'

const REFRESH_MS = 15_000

/** Where a tile leads: the queue (whole, or limited to one category) or the history. */
export type Target = { page: 'queue'; group?: Group } | { page: 'history' }

export default function Dashboard({ open }: { open: (target: Target) => void }) {
  const { t, msg, time } = useI18n()
  const [d, setD] = useState<D | null>(null)
  const [err, setErr] = useState('')
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [stale, setStale] = useState(false)  // the last background refresh failed: the numbers on screen are the previous ones
  const alive = useRef(true)
  const latest = useRef(0)  // the number of the newest request: the visibility refresh can overlap the scheduled one
  // quiet = a background refresh: if it fails the numbers already on screen stay (the "updated at" line shows their age)
  const fetchNow = useCallback(async (quiet: boolean) => {
    const mine = ++latest.current
    try {
      const fresh = await api.dashboard()
      if (!alive.current) return
      if (mine !== latest.current) return  // a newer request started meanwhile: this answer is older, never let it win
      setD(fresh); setUpdatedAt(new Date()); setErr(''); setStale(false)
    } catch (e) {
      // errorText: the ApiError's own message (msg() can translate it), never "Error: ..." and never a raw exception text
      if (alive.current && mine === latest.current) {
        if (quiet) setStale(true)  // keep the numbers, but say they are old (a banner under the "updated at" line)
        else setErr(errorText(e))
      }
    }
  }, [])
  const load = useCallback(() => { setErr(''); void fetchNow(false) }, [fetchNow])
  // The counters move while documents are being processed: refresh while the tab is visible, and as soon as it comes back.
  // Self-scheduling (the next wait starts when the answer is in), so the timer never stacks requests. Coming back to the tab
  // can still start one while the scheduled one is in flight: each request has a number, and an older answer is ignored.
  useEffect(() => {
    alive.current = true
    let timer: ReturnType<typeof setTimeout>
    const cycle = async () => {
      if (!document.hidden) await fetchNow(true)
      if (alive.current) timer = setTimeout(cycle, REFRESH_MS)
    }
    const onVisible = () => { if (!document.hidden) void fetchNow(true) }
    void fetchNow(false)
    timer = setTimeout(cycle, REFRESH_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => { alive.current = false; clearTimeout(timer); document.removeEventListener('visibilitychange', onVisible) }
  }, [fetchNow])
  if (err) {
    return (
      <div role="alert" className="space-y-2">
        <p className="text-rose-700">{msg(err)}</p>
        <Button variant="outline" size="sm" onClick={load}>{t('common.retry')}</Button>
      </div>
    )
  }
  if (!d) return <p role="status" className="text-slate-500">{t('common.loading')}</p>

  // each tile opens the screen it counts from: the pending ones, one category of the queue, or (for "Filed today") the history,
  // newest first so today's operations are at the top, but not filtered by date
  const tiles: [AskKey, number, string, Target][] = [
    ['dash.toProcess', d.pending, 'text-slate-900', { page: 'queue' }],
    ['dash.today', d.classified_today, 'text-emerald-700', { page: 'history' }],
    ['dash.needsValidation', d.needs_validation, 'text-amber-700', { page: 'queue', group: 'needs_validation' }],
    ['dash.ready', d.auto_ready, 'text-emerald-700', { page: 'queue', group: 'auto' }],
    ['dash.duplicates', d.duplicates, 'text-orange-700', { page: 'queue', group: 'duplicates' }],
    ['dash.errors', d.errors, d.errors ? 'text-rose-700' : 'text-slate-900', { page: 'queue', group: 'errors' }],
  ]
  return (
    <div className="space-y-6">
      {updatedAt && <p className="text-xs text-slate-500">{t('dash.updated', { at: time(updatedAt.toISOString()) })}</p>}
      {stale && <p role="alert" className="text-sm text-amber-800"><span aria-hidden="true">⚠ </span>{t('dash.stale')}</p>}
      {/* The counters refresh by themselves: a screen reader hears them when they CHANGE (this text only changes then; the
          "updated at" line above changes every 15 s and stays silent), not on each refresh */}
      <p role="status" className="sr-only">{tiles.map(([label, n]) => `${t(label)}: ${n}`).join(', ')}</p>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">{/* three narrow columns clipped the (longer) French titles */}
        {tiles.map(([label, n, cls, target]) => (
          // a real button: reachable with Tab, activated by Enter/Space, announced by screen readers
          // spans only: a <button> may hold phrasing content, and Card/CardHeader/CardContent are <div>s. Same look as the Card.
          <button key={label} type="button" onClick={() => open(target)}
            className="flex h-full cursor-pointer flex-col gap-4 overflow-hidden rounded-xl bg-card py-4 text-left text-sm text-card-foreground ring-1 ring-foreground/10 outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2">
            <span className="block px-4 text-sm font-medium text-slate-500">{t(label)}</span>
            <span className="block px-4"><span className={`text-4xl font-semibold ${cls}`}>{n}</span></span>
          </button>
        ))}
      </div>
      <Card>
        <CardHeader><CardTitle as="h2">{t('dash.sources')}</CardTitle></CardHeader>
        <CardContent className="text-sm">
          {d.sources.map((s) => (
            <div key={s.path} className="flex justify-between border-b py-2 last:border-0">
              <span>{t(s.kind === 'inbox' ? 'dash.srcInbox' : 'dash.srcBacklog')}<span className="ml-2 text-slate-500">{s.path}</span></span>
              <span className="font-medium">{t('dash.pdfCount', { n: s.files })}</span>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle as="h2">{t('dash.lastOps')}</CardTitle></CardHeader>
        <CardContent className="text-sm">
          {d.history.length === 0 && <span className="text-slate-500">{t('dash.noOps')}</span>}
          {d.history.map((o) => (
            <div key={o.id} className="border-b py-1 last:border-0">
              <span className="text-slate-500">{time(o.ts)}</span> · {opLabel(t, o.kind)}{o.undone ? ` ${t('dash.undone')}` : ''} · {baseName(o.dst)}
            </div>
          ))}
        </CardContent>
      </Card>
      <Accuracy />
    </div>
  )
}
