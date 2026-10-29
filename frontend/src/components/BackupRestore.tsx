import { useState } from 'react'
import { api, errorText, type RestoreResult } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'

/** Save the database, the learned corrections and the settings in one archive (optionally with a password), and put one back. */
export default function BackupRestore() {
  const { t, msg } = useI18n()
  const [password, setPassword] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [restorePassword, setRestorePassword] = useState('')
  const [withSettings, setWithSettings] = useState(false)
  const [busy, setBusy] = useState<'' | 'backup' | 'restore'>('')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')  // the name of the file just downloaded
  const [result, setResult] = useState<RestoreResult | null>(null)

  const backup = async () => {
    if (busy) return
    setBusy('backup'); setError(''); setSaved(''); setResult(null)
    try {
      const { blob, name } = await api.backup(password)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = name
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
      setSaved(name)
    } catch (e) {
      setError(errorText(e))
    }
    setBusy('')
  }

  const restore = async () => {
    if (busy || !file || !confirm(t('backup.confirmRestore'))) return  // declined: nothing is sent
    setBusy('restore'); setError(''); setSaved(''); setResult(null)
    try {
      setResult(await api.restore(file, restorePassword, withSettings))
    } catch (e) {
      setError(errorText(e))
    }
    setBusy('')
  }

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle as="h2">{t('backup.title')}</CardTitle></CardHeader>
      <CardContent className="max-w-2xl space-y-4 text-sm">
        <p className="text-slate-600">{t('backup.hint')}</p>
        <div className="space-y-2">
          <h3 className="font-medium">{t('backup.saveTitle')}</h3>
          <label className="flex flex-col gap-1 font-medium">{t('backup.password')}
            <Input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <p className="text-slate-600">{t('backup.passwordHint')}</p>
          <Button type="button" disabled={busy !== ''} onClick={() => void backup()}>{busy === 'backup' ? t('common.loading') : t('backup.save')}</Button>
        </div>
        <div className="space-y-2 border-t pt-4">
          <h3 className="font-medium">{t('backup.restoreTitle')}</h3>
          <label className="flex flex-col gap-1 font-medium">{t('backup.file')}
            <Input type="file" accept=".zip,application/zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <label className="flex flex-col gap-1 font-medium">{t('backup.restorePassword')}
            <Input type="password" autoComplete="off" value={restorePassword} onChange={(e) => setRestorePassword(e.target.value)} />
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={withSettings} onChange={(e) => setWithSettings(e.target.checked)} />
            {t('backup.withSettings')}
          </label>
          <Button type="button" variant="outline" disabled={busy !== '' || !file} onClick={() => void restore()}>
            {busy === 'restore' ? t('common.loading') : t('backup.restore')}
          </Button>
        </div>
        {/* live regions present before their text, so the outcome is announced */}
        <div role="status" className="empty:hidden text-emerald-800">
          {saved && t('backup.saved', { name: saved })}
          {result && t('backup.restored', { n: result.restored.length })}
        </div>
        <div role="alert" className="empty:hidden text-rose-700">{error && msg(error)}</div>
        {result && (
          <div className="space-y-1">
            {Object.entries(result.settings_skipped).map(([key, why]) => (
              <p key={key} className="text-amber-800">{t('backup.skipped', { key, why: msg(why) })}</p>
            ))}
            <p className="break-all text-slate-600">{t('backup.kept', { path: result.safety_copy })}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
