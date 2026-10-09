import { useEffect, useRef, useState } from 'react'
import { BookOpen, Search } from 'lucide-react'
import { post } from '../api'
import type { Citation } from '../types'

interface LookupResult {
  status: 'answered' | 'evidence' | 'not_covered' | 'no_match'
  answer: string
  citations: Citation[]
  evidence?: Citation[]
  model_error?: { reason: string; message: string } | null
}

export default function TermLookup({
  term,
  disabled,
  onCitation,
}: {
  term: string
  disabled: boolean
  onCitation: (citation: Citation) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<LookupResult | null>(null)
  const requestId = useRef(0)

  useEffect(() => {
    requestId.current += 1
    setBusy(false)
    setError('')
    setResult(null)
  }, [term])

  async function lookup() {
    if (!term) return
    setBusy(true)
    setError('')
    setResult(null)
    const currentRequest = ++requestId.current
    try {
      const response = await post<LookupResult>('/api/library/ask', {
        question: `What does "${term}" mean?`,
        scope: ['notes', 'guidelines', 'textbook'],
      })
      if (currentRequest !== requestId.current) return
      setResult(response)
      if (response.model_error) setError(response.model_error.message)
    } catch (failure) {
      if (currentRequest !== requestId.current) return
      setError((failure as Error).message)
    } finally {
      if (currentRequest === requestId.current) setBusy(false)
    }
  }

  const evidence = result?.evidence ?? []
  return <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold text-slate-700 flex items-center gap-2"><BookOpen size={14}/>Source term lookup</p>
        {term
          ? <p className="text-xs text-slate-500 mt-1 break-words">Selected: <span className="font-medium text-slate-700">{term}</span></p>
          : <p className="text-xs text-slate-400 mt-1">Select a term or short phrase in the encounter text.</p>}
      </div>
      <button type="button" className="btn !text-xs" disabled={disabled || busy || !term} onClick={lookup}>
        <Search size={14}/>{busy ? 'Looking up locally…' : 'Look up in library'}
      </button>
    </div>

    <div aria-live="polite">
    {error && <p role="alert" className="mt-3 text-xs text-red-700">{error}</p>}

    {result?.status === 'answered' && <div className="mt-3 border-t border-slate-200 pt-3">
      <p className="text-[10px] font-semibold tracking-wider text-teal-700">EXACT SOURCE EXCERPT</p>
      <blockquote className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{result.answer}</blockquote>
      <div className="flex flex-wrap gap-2 mt-3">{result.citations.map(item =>
        <button type="button" key={item.chunk_id} className="text-xs text-teal-700 underline" onClick={() => onCitation(item)}>
          {item.filename}, {item.location_type === 'section' ? 'section' : 'p.'} {item.page}
        </button>)}</div>
    </div>}

    {result?.status === 'evidence' && <div className="mt-3 border-t border-slate-200 pt-3">
      <p className="text-xs font-semibold text-amber-800">No verified definition was found.</p>
      <p className="text-xs text-slate-500 mt-1">These passages may mention the term. Review their context.</p>
      {evidence.slice(0, 2).map(item => <div key={item.chunk_id} className="mt-3 rounded-lg bg-white p-3">
        <blockquote className="whitespace-pre-wrap text-xs leading-relaxed text-slate-600">{item.snippet}</blockquote>
        <button type="button" className="text-xs text-teal-700 underline mt-2" onClick={() => onCitation(item)}>
          {item.filename}, {item.location_type === 'section' ? 'section' : 'p.'} {item.page}
        </button>
      </div>)}
    </div>}

    {(result?.status === 'not_covered' || result?.status === 'no_match') &&
      <p className="mt-3 border-t border-slate-200 pt-3 text-sm text-slate-600">Not covered by your library.</p>}
    </div>
  </div>
}
