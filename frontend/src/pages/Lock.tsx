import { useState } from 'react'
import { ArrowLeft, ArrowRight, FileLock2, KeyRound, LockKeyhole, ShieldCheck, WifiOff } from 'lucide-react'
import { post, setSession } from '../api'
import { BrandMark } from '../components/Brand'
import RecoveryKeyCard from '../components/RecoveryKeyCard'

interface UnlockResponse {
  token: string
  created: boolean
  recovery_configured: boolean
  recovery_prompt: boolean
}

interface RecoverResponse {
  token: string
  recovery_configured: boolean
  recovery_key: string | null
}

type Mode = 'password' | 'setup' | 'recovery' | 'key'

export default function Lock({
  initialized,
  recoveryConfigured,
  onUnlock,
}: {
  initialized: boolean
  recoveryConfigured: boolean
  onUnlock: (token: string) => void
}) {
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [recoveryKeyInput, setRecoveryKeyInput] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newConfirmation, setNewConfirmation] = useState('')
  const [replaceRecovery, setReplaceRecovery] = useState(true)
  const [displayedRecoveryKey, setDisplayedRecoveryKey] = useState('')
  const [pendingToken, setPendingToken] = useState('')
  const [mode, setMode] = useState<Mode>('password')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function finish(token: string) {
    setDisplayedRecoveryKey('')
    setPendingToken('')
    setPassword('')
    setConfirmation('')
    onUnlock(token)
  }

  async function submitPassword(event: React.FormEvent) {
    event.preventDefault(); setError('')
    if (!initialized && password !== confirmation) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      const result = await post<UnlockResponse>('/api/unlock', {password})
      setPassword(''); setConfirmation('')
      if (result.recovery_prompt) {
        setSession(result.token)
        setPendingToken(result.token)
        setMode('setup')
      } else {
        finish(result.token)
      }
    } catch (failure) {
      setSession(null)
      setError((failure as Error).message)
      setPassword(''); setConfirmation('')
    } finally { setBusy(false) }
  }

  async function setupRecovery(enabled: boolean) {
    setBusy(true); setError('')
    try {
      const result = await post<{configured: boolean; recovery_key: string | null}>('/api/vault/recovery/setup', {enabled})
      if (result.recovery_key) {
        setDisplayedRecoveryKey(result.recovery_key)
        setMode('key')
      } else {
        finish(pendingToken)
      }
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }

  async function recover(event: React.FormEvent) {
    event.preventDefault(); setError('')
    if (newPassword !== newConfirmation) { setError('New passwords do not match.'); return }
    setBusy(true)
    try {
      const result = await post<RecoverResponse>('/api/vault/recover', {
        recovery_key: recoveryKeyInput,
        new_password: newPassword,
        generate_new_recovery: replaceRecovery,
      })
      setRecoveryKeyInput(''); setNewPassword(''); setNewConfirmation('')
      setSession(result.token)
      if (result.recovery_key) {
        setPendingToken(result.token)
        setDisplayedRecoveryKey(result.recovery_key)
        setMode('key')
      } else {
        finish(result.token)
      }
    } catch (failure) {
      setError((failure as Error).message)
      setRecoveryKeyInput('')
    } finally { setBusy(false) }
  }

  let card: React.ReactNode
  if (mode === 'setup') {
    card = <>
      <h2 className="text-2xl font-semibold tracking-tight">Create a recovery key?</h2>
      <p className="mt-2 text-sm leading-relaxed text-slate-500">A recovery key lets you set a new password if you forget the current one. It is generated locally and shown once.</p>
      <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-relaxed text-amber-900">If you forget your password or lose this device, your data cannot be recovered without a recovery key.</div>
      {error && <p role="alert" className="error mt-5">{error}</p>}
      <div className="mt-6 space-y-3">
        <button type="button" className="btn-primary w-full" disabled={busy} onClick={() => setupRecovery(true)}><KeyRound size={16}/>{busy ? 'Generating locally…' : 'Create recovery key'}</button>
        <button type="button" className="btn w-full" disabled={busy} onClick={() => setupRecovery(false)}>Continue without recovery</button>
      </div>
    </>
  } else if (mode === 'key') {
    card = <RecoveryKeyCard recoveryKey={displayedRecoveryKey} title="Store your new recovery key" onDone={() => finish(pendingToken)}/>
  } else if (mode === 'recovery') {
    card = <>
      <button type="button" className="mb-5 flex items-center gap-2 text-xs text-teal-800" onClick={() => {setMode('password'); setError('')}}><ArrowLeft size={14}/>Back to password</button>
      <h2 className="text-2xl font-semibold tracking-tight">Recover your vault.</h2>
      <p className="mt-2 mb-7 text-sm leading-relaxed text-slate-500">Enter your recovery key and choose a new password. The old password and old recovery key will stop working.</p>
      <form onSubmit={recover} className="space-y-5">
        <div><label className="field-label" htmlFor="recovery-key">Recovery key</label><textarea className="mt-2 font-mono" id="recovery-key" rows={3} autoComplete="off" required maxLength={128} value={recoveryKeyInput} onChange={event => setRecoveryKeyInput(event.target.value)}/></div>
        <div><label className="field-label" htmlFor="new-password">New vault password · at least 12 characters</label><input className="mt-2" id="new-password" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required value={newPassword} onChange={event => setNewPassword(event.target.value)}/></div>
        <div><label className="field-label" htmlFor="new-confirmation">Confirm new password</label><input className="mt-2" id="new-confirmation" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required value={newConfirmation} onChange={event => setNewConfirmation(event.target.value)}/></div>
        <label className="flex items-start gap-3 text-xs leading-relaxed text-slate-600"><input type="checkbox" className="!mt-0.5 !w-auto accent-teal-800" checked={replaceRecovery} onChange={event => setReplaceRecovery(event.target.checked)}/>Generate a replacement recovery key after recovery.</label>
        {error && <p role="alert" className="error">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>{busy ? 'Recovering locally…' : 'Set new password and recover'}<ArrowRight size={16}/></button>
      </form>
    </>
  } else {
    card = <>
      <div className="mb-6 grid h-12 w-12 place-items-center rounded-xl bg-teal-50 text-teal-800"><LockKeyhole size={23}/></div>
      <h2 className="text-2xl font-semibold tracking-tight">{initialized ? 'Welcome back.' : 'Create your local vault.'}</h2>
      <p className="mt-2 mb-7 text-sm leading-relaxed text-slate-500">{initialized ? 'Unlock to access your encrypted drafts and library. Your password stays on this device.' : 'Choose a password or passphrase. You can optionally create a one-time recovery key next.'}</p>
      <form onSubmit={submitPassword} className="space-y-5">
        <div><label className="field-label" htmlFor="password">Vault password</label><input className="mt-2" id="password" type="password" autoComplete={initialized ? 'current-password' : 'new-password'} minLength={initialized ? 1 : 12} maxLength={1024} required value={password} onChange={event => setPassword(event.target.value)}/></div>
        {!initialized && <div><label className="field-label" htmlFor="confirmation">Confirm password · at least 12 characters</label><input className="mt-2" id="confirmation" type="password" autoComplete="new-password" minLength={12} maxLength={1024} required value={confirmation} onChange={event => setConfirmation(event.target.value)}/></div>}
        {error && <p role="alert" className="error">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>{busy ? 'Unlocking and loading your local library…' : initialized ? 'Unlock workspace' : 'Create encrypted vault'}<ArrowRight size={16}/></button>
        {initialized && recoveryConfigured && <button type="button" className="w-full text-xs font-medium text-teal-800 underline" onClick={() => {setMode('recovery'); setError('')}}>Forgot password? Use recovery key</button>}
        {busy && initialized && <p role="status" className="text-xs leading-relaxed text-slate-500">The first unlock after the storage update may take longer while a verified encrypted backup is created and the vault is migrated.</p>}
      </form>
      <p className="mt-6 border-t border-slate-100 pt-5 text-xs leading-relaxed text-slate-400">Auto-lock clears the session key and visible drafts after inactivity. Unsaved drafts are discarded when you lock.</p>
    </>
  }

  return <div className="lock-page mx-auto grid max-w-6xl items-center gap-8 py-10 lg:grid-cols-[1.1fr_.9fr]">
    <div className="welcome-hero"><div className="welcome-lead"><BrandMark className="mb-8 h-14 w-14 text-[#294c3c]"/><p className="eyebrow">YOUR DEVICE. YOUR WORKSPACE.</p><h1 className="mt-5 text-5xl font-semibold leading-[1.12] tracking-tight">No signal.<br/><span>Still thinking.</span></h1></div><div className="welcome-details"><p className="mt-6 max-w-md text-base leading-relaxed">Meet TIBOQ, your private AI companion for medical study and encounter documentation practice. Find knowledge from your own sources, organize practice notes, and work without the cloud.</p><div className="mt-8 space-y-4 text-sm"><p className="flex items-center gap-3"><WifiOff size={18}/> Local models. No cloud processing.</p><p className="flex items-center gap-3"><FileLock2 size={18}/> Encrypted records and library.</p><p className="flex items-center gap-3"><ShieldCheck size={18}/> Your review is always the final step.</p></div><p className="mt-10 text-xs">Built for students, interns, and careful documentation.</p></div></div>
    <section className="vault-card panel p-8 shadow-sm">{card}</section>
  </div>
}
