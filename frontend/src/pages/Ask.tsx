import { useRef, useState } from 'react'
import { ArrowUp, BookOpen, MessageSquareText } from 'lucide-react'
import { ApiError, post } from '../api'
import type { Citation } from '../types'
import CitationView from '../components/CitationView'

interface AskResult {
  status: 'answered' | 'evidence' | 'not_covered' | 'no_match'
  answer: string
  citations: Citation[]
  evidence?: Citation[]
  model_error?: { reason: string; message: string } | null
}

export default function Ask() {
  const [question, setQuestion] = useState('')
  const [scope, setScope] = useState(['notes', 'guidelines', 'textbook'])
  const [result, setResult] = useState<AskResult | null>(null)
  const [selected, setSelected] = useState<Citation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [modelError, setModelError] = useState(false)
  const form = useRef<HTMLFormElement>(null)

  async function ask(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true); setError(''); setModelError(false); setResult(null); setSelected(null)
    try {
      const response = await post<AskResult>('/api/library/ask', { question, scope })
      setResult(response)
      if (response.model_error) {
        setModelError(true); setError(response.model_error.message)
      }
    } catch (e) {
      setModelError(e instanceof ApiError && e.code === 'model_error')
      setError((e as Error).message)
    } finally { setBusy(false) }
  }

  function sourceButton(citation: Citation) {
    return <button className="btn !text-xs !py-2 text-teal-800" onClick={() => setSelected(citation)}>
      {citation.filename}, {citation.location_type === 'section' ? 'section' : 'p.'} {citation.page} · View context
    </button>
  }

  return <div className="max-w-4xl mx-auto">
    <p className="eyebrow">ANSWERS WITH A PAPER TRAIL</p>
    <h1 className="mt-2 text-3xl font-semibold tracking-tight">Ask your sources.</h1>
    <p className="text-sm text-slate-500 mt-2 mb-7">Search indexed sources locally. AI-selected answers and retrieved evidence are labeled separately.</p>
    <section className="panel p-6">
      <div className="flex flex-wrap gap-4 items-center mb-5"><span className="text-xs font-semibold text-slate-500">Search in</span>
        {[['notes', 'My notes'], ['guidelines', 'Guidelines'], ['textbook', 'Textbooks']].map(([id, label]) =>
          <label key={id} className="text-xs flex items-center gap-2 text-slate-600"><input type="checkbox" className="!w-auto accent-teal-800" disabled={busy} checked={scope.includes(id)} onChange={e => setScope(prev => e.target.checked ? [...prev, id] : prev.filter(s => s !== id))} />{label}</label>)}
      </div>
      <form ref={form} onSubmit={ask}>
        <label htmlFor="question" className="sr-only">Ask a question from your local library</label>
        <textarea id="question" rows={3} maxLength={2000} value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} placeholder="What should my chest pain presentation document?" />
        <div className="flex items-center justify-between mt-4 gap-3"><p className="text-[11px] text-slate-400 flex items-center gap-2"><BookOpen size={14} />Only indexed sources are searched.</p>
          <button className="btn-primary" disabled={busy || !question.trim() || !scope.length}>{busy ? 'Searching locally…' : 'Ask library'}<ArrowUp size={16} /></button>
        </div>
      </form>
    </section>

    {error && <div role="alert" className="error mt-5"><p className="font-semibold">{modelError ? 'Local answer model error' : 'Local search could not be completed'}</p><p className="mt-1">{error}</p><p className="text-xs mt-2">This error does not establish whether your library covers the question.</p><button className="btn !text-xs mt-3" disabled={busy} onClick={() => form.current?.requestSubmit()}>Retry question</button></div>}

    {result?.status === 'answered' && <section className="panel p-6 mt-6" aria-live="polite">
      <h2 className="text-sm font-semibold">Source-backed answer</h2>
      <p className="text-xs text-slate-500 mt-2">The complete answer text matches an indexed source passage. Relevance and coverage of your whole question still need review.</p>
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700 mt-4">{result.answer}</p>
      <div className="flex flex-wrap gap-2 mt-5">{result.citations.map(c => <div key={c.chunk_id}>{sourceButton(c)}</div>)}</div>
    </section>}

    {result?.status === 'evidence' && <section className="panel p-6 mt-6" aria-live="polite">
      <h2 className="text-sm font-semibold">Potentially relevant source passages</h2>
      <p className="text-xs text-slate-500 mt-2">These are retrieved excerpts, not a validated answer. Matches may address only part of your question; missing details have not been supplied.</p>
      <p className="text-xs text-slate-500 mt-2">Shown using similarity and query-term matches. Relevance is uncertain; review the source context.</p>
      {result.evidence?.map(c => <article key={c.chunk_id} className="mt-5 border-t border-slate-100 pt-5">
        <blockquote className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-700 mb-3">{c.snippet}</blockquote>
        {sourceButton(c)}
      </article>)}
    </section>}

    {(result?.status === 'not_covered' || result?.status === 'no_match') && <section className="panel p-6 mt-6" aria-live="polite">
      <h2 className="text-sm font-semibold">No confident source match</h2>
      {result.answer && <p className="text-sm mt-3">{result.answer}</p>}
      <p className="text-xs text-slate-500 mt-2">No passage met the matching checks and no source-backed answer is available. This is not proof that the information is absent. Try a more specific question or another source scope.</p>
    </section>}

    {!result && !error && !busy && <div className="text-center py-16"><MessageSquareText size={33} className="mx-auto mb-5 text-slate-300" /><h2 className="text-base font-medium text-slate-600">Begin with something you're learning.</h2><p className="text-xs text-slate-400 mt-2">No sources yet? Load the sample library from My library.</p><div className="flex flex-wrap justify-center gap-2 mt-6">{['What does SOAP stand for?', 'What chest pain details should I document?', 'What fever details should I document?'].map(sample => <button key={sample} className="btn !text-xs" onClick={() => setQuestion(sample)}>{sample}</button>)}</div></div>}
    {selected && <CitationView citation={selected} onClose={() => setSelected(null)} />}
  </div>
}
