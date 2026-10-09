import { useState } from 'react'
import { LockKeyhole, ArrowRight, ShieldCheck, FileLock2, WifiOff } from 'lucide-react'
import { post } from '../api'
import { BrandMark } from '../components/Brand'
export default function Lock({ initialized, onUnlock }: { initialized: boolean; onUnlock: (token: string) => void }) {
  const [password, setPassword] = useState(''); const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError('')
    if (!initialized && password !== confirmation) { setError('Passwords do not match.'); return }
    setBusy(true)
    try { const result = await post<{token: string}>('/api/unlock', {password}); setPassword(''); setConfirmation(''); onUnlock(result.token) }
    catch (e) { setError((e as Error).message); setPassword(''); setConfirmation('') } finally { setBusy(false) }
  }
  return <div className="lock-page mx-auto grid max-w-6xl items-center gap-8 py-10 lg:grid-cols-[1.1fr_.9fr]">
    <div className="welcome-hero"><div className="welcome-lead"><BrandMark className="w-14 h-14 text-[#294c3c] mb-8"/><p className="eyebrow">YOUR DEVICE. YOUR WORKSPACE.</p><h1 className="mt-5 text-5xl font-semibold leading-[1.12] tracking-tight">No signal.<br/><span>Still thinking.</span></h1></div><div className="welcome-details"><p className="mt-6 max-w-md text-base leading-relaxed">Meet TIBOQ, your private AI companion for medical study and encounter documentation practice. Find knowledge from your own sources, organize practice notes, and work without the cloud.</p><div className="mt-8 space-y-4 text-sm"><p className="flex gap-3 items-center"><WifiOff size={18}/> Local models. No cloud processing.</p><p className="flex gap-3 items-center"><FileLock2 size={18}/> Encrypted records and library.</p><p className="flex gap-3 items-center"><ShieldCheck size={18}/> Your review is always the final step.</p></div><p className="text-xs mt-10">Built for students, interns, and careful documentation.</p></div></div>
    <section className="vault-card panel p-8 shadow-sm"><div className="w-12 h-12 rounded-xl bg-teal-50 text-teal-800 grid place-items-center mb-6"><LockKeyhole size={23}/></div><h2 className="text-2xl font-semibold tracking-tight">{initialized ? 'Welcome back.' : 'Create your local vault.'}</h2><p className="mt-2 mb-7 text-sm leading-relaxed text-slate-500">{initialized ? 'Unlock to access your encrypted drafts and library. Your password stays on this device.' : 'Set a password to encrypt your workspace. It is never stored and cannot be recovered.'}</p>
      <form onSubmit={submit} className="space-y-5"><div><label className="field-label" htmlFor="password">Vault password</label><input className="mt-2" id="password" type="password" autoComplete={initialized ? 'current-password' : 'new-password'} minLength={initialized ? 1 : 10} maxLength={1024} required value={password} onChange={e => setPassword(e.target.value)}/></div>{!initialized && <div><label className="field-label" htmlFor="confirmation">Confirm password · at least 10 characters</label><input className="mt-2" id="confirmation" type="password" autoComplete="new-password" required value={confirmation} onChange={e => setConfirmation(e.target.value)}/></div>}{error && <p role="alert" className="error">{error}</p>}<button className="btn-primary w-full" disabled={busy}>{busy ? 'Unlocking and loading your local library…' : initialized ? 'Unlock workspace' : 'Create encrypted vault'}<ArrowRight size={16}/></button>{busy && initialized && <p role="status" className="text-xs leading-relaxed text-slate-500">The first unlock after the storage update may take longer while existing encrypted library items are upgraded once.</p>}</form><p className="mt-6 pt-5 border-t border-slate-100 text-xs leading-relaxed text-slate-400">Auto-lock clears the session key and visible drafts after inactivity. Unsaved drafts are discarded when you lock.</p>
    </section>
  </div>
}
