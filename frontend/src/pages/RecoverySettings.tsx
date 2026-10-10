import { useState } from 'react'
import { KeyRound, RefreshCw } from 'lucide-react'
import { post } from '../api'
import RecoveryKeyCard from '../components/RecoveryKeyCard'

interface RecoveryResponse { configured: boolean; recovery_key: string | null }

export default function RecoverySettings({ configured, refresh }: { configured: boolean; refresh: () => void }) {
  const [password, setPassword] = useState('')
  const [recoveryKey, setRecoveryKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function create() {
    setBusy(true); setError('')
    try {
      const result = await post<RecoveryResponse>('/api/vault/recovery/setup', {enabled: true})
      setRecoveryKey(result.recovery_key ?? '')
      refresh()
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }

  async function regenerate(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = await post<RecoveryResponse>('/api/vault/recovery/regenerate', {current_password: password})
      setPassword('')
      setRecoveryKey(result.recovery_key ?? '')
      refresh()
    } catch (failure) { setError((failure as Error).message); setPassword('') }
    finally { setBusy(false) }
  }

  return <div className="mx-auto max-w-2xl">
    <p className="eyebrow">VAULT SETTINGS</p>
    <h1 className="mt-3 text-3xl font-semibold tracking-tight">Recovery key.</h1>
    <p className="mt-3 text-sm leading-relaxed text-slate-500">A recovery key can reset your password while keeping encrypted records and library sources readable.</p>
    <section className="panel mt-6 p-6">
      <div className="flex items-start gap-4">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-teal-50 text-teal-800"><KeyRound size={19}/></div>
        <div>
          <h2 className="text-lg font-semibold">{configured ? 'Recovery is configured' : 'No recovery key configured'}</h2>
          <p className="mt-2 text-xs leading-relaxed text-slate-500">{configured
            ? 'Regenerating immediately invalidates the old recovery key and requires your current password.'
            : 'If you forget your password or lose this device, your data cannot be recovered.'}</p>
        </div>
      </div>
      {error && <p role="alert" className="error mt-5">{error}</p>}
      {!recoveryKey && (configured
        ? <form className="mt-6 space-y-4" onSubmit={regenerate}>
            <div><label className="field-label" htmlFor="recovery-current-password">Current vault password</label><input className="mt-2" id="recovery-current-password" type="password" autoComplete="current-password" required maxLength={1024} value={password} onChange={event => setPassword(event.target.value)}/></div>
            <button className="btn-primary" disabled={busy || !password}><RefreshCw size={15}/>{busy ? 'Regenerating…' : 'Regenerate recovery key'}</button>
          </form>
        : <button type="button" className="btn-primary mt-6" disabled={busy} onClick={create}><KeyRound size={15}/>{busy ? 'Generating…' : 'Create recovery key'}</button>)}
      {recoveryKey && <div className="mt-6"><RecoveryKeyCard recoveryKey={recoveryKey} title={configured ? 'Your new recovery key' : 'Your recovery key'} onDone={() => {setRecoveryKey(''); refresh()}}/></div>}
    </section>
  </div>
}
