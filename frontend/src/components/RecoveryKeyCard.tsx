import { useState } from 'react'
import { Check, Copy, Printer } from 'lucide-react'

export default function RecoveryKeyCard({
  recoveryKey,
  title = 'Store your recovery key',
  onDone,
}: {
  recoveryKey: string
  title?: string
  onDone: () => void
}) {
  const [confirmed, setConfirmed] = useState(false)
  const [copyStatus, setCopyStatus] = useState('')

  async function copy() {
    try {
      await navigator.clipboard.writeText(recoveryKey)
      setCopyStatus('Copied')
    } catch {
      setCopyStatus('Copy failed. Select the key and copy it manually.')
    }
  }

  return <div className="recovery-key-print fixed inset-0 z-[60] grid place-items-center overflow-auto bg-slate-950/50 p-5" role="dialog" aria-modal="true" aria-label={title}>
  <section className="w-full max-w-xl rounded-xl border border-amber-200 bg-amber-50 p-5 shadow-xl">
    <p className="eyebrow">ONE-TIME DISPLAY</p>
    <h3 className="mt-2 text-lg font-semibold text-slate-900">{title}</h3>
    <p className="mt-2 text-xs leading-relaxed text-slate-600">This key can reset your vault password. It will not be shown again. Store it somewhere private and separate from this device.</p>
    <code className="mt-4 block select-all break-all rounded-lg border border-amber-200 bg-white p-4 text-sm font-semibold leading-7 tracking-wider text-slate-900">{recoveryKey}</code>
    <div className="mt-4 flex flex-wrap gap-2 print:hidden">
      <button type="button" className="btn !text-xs" onClick={copy}><Copy size={14}/>Copy</button>
      <button type="button" className="btn !text-xs" onClick={() => window.print()}><Printer size={14}/>Print</button>
      {copyStatus && <span role="status" className="self-center text-xs text-slate-600">{copyStatus}</span>}
    </div>
    <label className="mt-5 flex items-start gap-3 text-xs leading-relaxed text-slate-700 print:hidden">
      <input type="checkbox" className="!mt-0.5 !w-auto accent-teal-800" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>
      I have stored this recovery key safely and understand that it cannot be shown again.
    </label>
    <button type="button" className="btn-primary mt-4 w-full print:hidden" disabled={!confirmed} onClick={onDone}>
      <Check size={16}/>Continue
    </button>
  </section>
  </div>
}
