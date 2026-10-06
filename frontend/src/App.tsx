import { useEffect, useState } from 'react'
import { api, errorText } from '@/api'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { I18nProvider, LangSwitch, useI18n } from '@/i18n'
import Dashboard, { type Target } from '@/pages/Dashboard'
import History from '@/pages/History'
import Notes from '@/pages/Notes'
import Settings from '@/pages/Settings'
import Rules from '@/pages/Rules'
import Search from '@/pages/Search'
import Queue from '@/pages/Queue'
import { parseHash, toHash, type Page, type Route } from '@/route'

function Shell() {
  const { t, msg } = useI18n()
  const [auth, setAuth] = useState<boolean | null>(null)
  // the page (and the queue's category, set by a dashboard tile) live in the URL hash: reload, Back/Forward, bookmarks and
  // shared links all work. Navigating only writes the hash; the hashchange listener is the one place that sets the state.
  const [{ page, group }, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const sync = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const go = (route: Route) => { window.location.hash = toHash(route) }
  const open = (target: Target) => go({ page: target.page, group: target.page === 'queue' ? target.group ?? null : null })
  // the raw server text of a failed session check: an outage is not a logout (/auth/me answers 200 for an anonymous visitor)
  const [failure, setFailure] = useState('')
  const [version, setVersion] = useState('')  // the program's version, from the server (written once, in pyproject.toml)
  const refresh = () => api.me().then((m) => { setAuth(m.authenticated); setVersion(m.version) })
    .catch((e) => setFailure(errorText(e)))
  useEffect(() => {
    // The desktop application opens the page as /?t=<token>: sign in with it, then take it out of the address at once.
    const token = new URLSearchParams(window.location.search).get('t')
    const start = async () => {
      if (token) {
        try { await api.me(); await api.localLogin(token) } catch { /* wrong token: the message below says what to do */ }
        window.history.replaceState(null, '', window.location.pathname + window.location.hash)
      }
      await refresh()
    }
    void start().catch((e) => setFailure(errorText(e)))
  }, [])
  // a first run (no inbox / library chosen yet) opens the Settings screen, once the user is signed in
  const [checkedSetup, setCheckedSetup] = useState(false)
  useEffect(() => {
    if (!auth || checkedSetup) return
    setCheckedSetup(true)
    api.settings().then((s) => { if (!s.configured) window.location.hash = '#settings' }).catch(() => {})
  }, [auth, checkedSetup])
  if (failure) {
    return (
      <div role="alert" className="mx-auto max-w-md space-y-3 p-4">
        <p className="rounded bg-rose-50 p-2 text-sm text-rose-900"><span aria-hidden="true">✕ </span>{t('app.sessionFailed')} {msg(failure)}</p>
        <Button onClick={() => { setFailure(''); refresh() }}>{t('common.retry')}</Button>
      </div>
    )
  }
  // not a blank page while the session is being checked: a slow network must not look like a broken application
  if (auth === null) return <p role="status" className="p-4 text-slate-500">{t('common.loading')}</p>
  // the launcher signs the window in; if that did not happen (the page was opened some other way), say what to do
  if (!auth) return <p role="alert" className="mx-auto max-w-md p-4 text-rose-700">{t('app.notSignedIn')}</p>
  return (
    // ONE Tabs around the header and the pages: a tab is only a tab if a tabpanel belongs to it
    <Tabs value={page} onValueChange={(v) => go({ page: v as Page, group: null })}
      className="mx-auto max-w-[110rem] gap-0 p-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h1 className="text-xl font-semibold">{t('app.title')}{version && <span className="ml-2 text-xs font-normal text-slate-600">v{version}</span>}</h1>
        {/* the height is in rem (it grows with the text size); a row wider than the screen scrolls instead of being cut off */}
        <TabsList className="max-w-full overflow-x-auto">
          <TabsTrigger value="dashboard">{t('nav.dashboard')}</TabsTrigger>
          <TabsTrigger value="queue">{t('nav.queue')}</TabsTrigger>
          <TabsTrigger value="history">{t('nav.history')}</TabsTrigger>
          <TabsTrigger value="search">{t('nav.search')}</TabsTrigger>
          <TabsTrigger value="rules">{t('nav.rules')}</TabsTrigger>
          <TabsTrigger value="settings">{t('nav.settings')}</TabsTrigger>
          <TabsTrigger value="notes">{t('nav.notes')}</TabsTrigger>
        </TabsList>
        <div className="flex items-center gap-2">
          <LangSwitch />
        </div>
      </header>
      {/* text-base: the panel's own text-sm would shrink every page */}
      <TabsContent value="dashboard" className="text-base"><Dashboard open={open} /></TabsContent>
      <TabsContent value="queue" className="text-base"><Queue group={group} onShowAll={() => go({ page: 'queue', group: null })} /></TabsContent>
      <TabsContent value="history" className="text-base"><History /></TabsContent>
      <TabsContent value="search" className="text-base"><Search /></TabsContent>
      <TabsContent value="rules" className="text-base"><Rules /></TabsContent>
      <TabsContent value="settings" className="text-base"><Settings onSaved={() => go({ page: 'queue', group: null })} /></TabsContent>
      <TabsContent value="notes" className="text-base"><Notes /></TabsContent>
    </Tabs>
  )
}

export default function App() {
  return <I18nProvider><Shell /></I18nProvider>
}
