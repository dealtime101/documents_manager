import { useState } from 'react'
import { api, ApiError, errorText } from '@/api'
import { Field } from '@/components/Bits'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { LangSwitch, useI18n } from '@/i18n'

export default function Login({ onDone }: { onDone: () => void }) {
  const { t, msg } = useI18n()
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState('')
  const [refused, setRefused] = useState(false)  // the last error was a refusal of the login (HTTP 401), not a network or server failure
  const [busy, setBusy] = useState(false)  // one login request at a time: no double submit, and the wait is visible
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setErr('')
    setRefused(false)
    let signedIn = false
    try {
      await api.login(u, p)
      signedIn = true
    } catch (x) {
      setErr(errorText(x))
      setRefused(x instanceof ApiError && x.status === 401)  // only a REFUSED login says the entries are wrong; a network or server failure does not
    }
    setBusy(false)
    if (signedIn) onDone()  // outside the try: what happens AFTER a good login is not a failed login, whatever it throws
  }
  // the fields point at the message; they say they are WRONG only when the server refused the login
  const invalid = err ? { 'aria-describedby': 'login-error', ...(refused ? { 'aria-invalid': true } : {}) } : {}
  return (
    <div className="grid min-h-screen place-items-center bg-slate-50 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle as="h1">{t('app.title')}</CardTitle>
          <LangSwitch />
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-3">
            <Field label={t('login.username')}><Input autoFocus required autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} {...invalid} /></Field>
            <Field label={t('login.password')}><Input type="password" required autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} {...invalid} /></Field>
            {/* a live region that is in the page BEFORE its text arrives, or the failure is not announced: never display:none.
                Empty, it has no height; `empty:m-0` drops the space-y gap it would otherwise add above the button */}
            <div id="login-error" role="alert" className="empty:m-0">
              {err && <p className="text-sm text-rose-700"><span aria-hidden="true">✕ </span>{msg(err)}</p>}
            </div>
            <Button type="submit" className="w-full" disabled={busy} aria-busy={busy}>{t(busy ? 'login.busy' : 'login.submit')}</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
