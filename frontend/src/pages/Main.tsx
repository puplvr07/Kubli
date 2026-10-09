import { useEffect, useState } from 'react'
import { FileText, WandSparkles, Check, Eraser, Download, Trash2, ClipboardCheck, AlertTriangle, Save } from 'lucide-react'
import { api, post, downloadPdf } from '../api'
import { blankRecord, type RecordDraft, type Warning, type DeidFlag, type SavedRecord, type Citation } from '../types'
import ReviewForm, { fields, valueAt, updateAt } from '../components/ReviewForm'
import CitationView from '../components/CitationView'
import VoiceRecorder from '../components/VoiceRecorder'
export default function Main({ demo, refresh }: { demo: boolean; refresh: () => void }) {
  const [voiceKey, setVoiceKey] = useState(0)
  const [text, setText] = useState(''); const [record, setRecord] = useState<RecordDraft>(blankRecord)
  const [pending, setPending] = useState(new Set<string>()); const [warnings, setWarnings] = useState<Warning[]>([])
  const [modelWarnings, setModelWarnings] = useState<Warning[]>([]); const [flags, setFlags] = useState<DeidFlag[]>([])
  const [kept, setKept] = useState(new Set<string>()); const [ack, setAck] = useState(new Set<string>())
  const [busy, setBusy] = useState(''); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const [saved, setSaved] = useState<SavedRecord[]>([]); const [selected, setSelected] = useState<string | null>(null)
  const [completeness, setCompleteness] = useState<{item: string; citation: Citation}[]>([]); const [checkMessage, setCheckMessage] = useState('')
  const [citation, setCitation] = useState<Citation | null>(null); const [deleteId, setDeleteId] = useState<string | null>(null)
  function fail(e: unknown) { setError((e as Error).message) }
  async function loadRecords() { try { setSaved(await api<SavedRecord[]>('/api/records')) } catch (e) { fail(e) } }
  useEffect(() => { void loadRecords() }, [])
  useEffect(() => {
    const timer = setTimeout(() => { post<{flags: DeidFlag[]; warnings: Warning[]}>('/api/review', record).then(r => {setFlags(r.flags); setWarnings(r.warnings)}).catch(fail) }, 400)
    return () => clearTimeout(timer)
  }, [record])
  useEffect(() => {
    if (demo) {
      post<{text: string; record: RecordDraft}>('/api/demo/presentation', {}).then(sample => {
        setText(sample.text); setRecord(sample.record); setPending(new Set(fields.filter(([p]) => valueAt(sample.record, p)).map(([p]) => p)))
        setNotice('Prewritten fictional demo draft loaded. Review it before saving.'); setSelected(null); setKept(new Set()); setAck(new Set())
      }).catch(fail)
    }
  }, [demo])
  function edit(next: RecordDraft, path: string) {
    setRecord(next); setPending(prev => {const s = new Set(prev); s.delete(path); return s})
    setKept(new Set()); setAck(new Set()); setSelected(null); setCompleteness([]); setCheckMessage(''); setNotice('')
    setModelWarnings(prev => prev.filter(w => w.field !== path))
  }
  async function structure() {
    setBusy('structure'); setError(''); setNotice('')
    try {
      const result = await post<{record: RecordDraft; warnings: Warning[]}>('/api/structure', {text})
      setRecord(result.record); setModelWarnings(result.warnings.filter(w => w.message.startsWith('Unsupported')))
      setWarnings(result.warnings.filter(w => !w.message.startsWith('Unsupported')))
      setPending(new Set(fields.filter(([p]) => valueAt(result.record, p)).map(([p]) => p)))
      setKept(new Set()); setAck(new Set()); setSelected(null); setCompleteness([]); setCheckMessage('')
    } catch (e) { fail(e) } finally { setBusy('') }
  }
  function clear() { setVoiceKey(prev => prev + 1); setText(''); setRecord(blankRecord()); setPending(new Set()); setWarnings([]); setFlags([]); setKept(new Set()); setAck(new Set()); setModelWarnings([]); setSelected(null); setNotice(''); setError(''); setCompleteness([]); setCheckMessage('') }
  async function confirmSave() {
    setBusy('save'); setError('')
    try {
      const review = await post<{flags: DeidFlag[]; warnings: Warning[]}>('/api/review', record)
      setFlags(review.flags); setWarnings(review.warnings)
      if (pending.size) throw new Error('Review or edit every highlighted field before saving.')
      if (review.flags.some(f => !kept.has(f.id))) throw new Error('Remove or explicitly keep every identifier before saving.')
      if (review.warnings.some(w => !ack.has(w.message))) throw new Error('Confirm every numeric warning before saving.')
      const result = await post<{id: string}>('/api/records', {record, confirmed: true, deid_keep: [...kept], warning_acknowledgements: [...ack]})
      setSelected(result.id); setNotice('Reviewed draft saved to your encrypted local vault.'); await loadRecords(); refresh()
    } catch (e) { fail(e) } finally { setBusy('') }
  }
  function removeFlag(flag: DeidFlag) {
    if (!flag.field) return
    const field = fields.find(([p]) => p === flag.field)
    if (!field) return
    const value = valueAt(record, flag.field)
    edit(updateAt(record, flag.field, Array.from(value).slice(0, flag.start).join('') + Array.from(value).slice(flag.end).join(''), field[2]), flag.field)
  }
  async function check() { setBusy('check'); setError(''); try {
    const result = await post<{flags: {item: string; citation: Citation}[]; message: string}>('/api/completeness', {record})
    setCompleteness(result.flags); setCheckMessage(result.message)
  } catch (e) { fail(e) } finally { setBusy('') } }
  async function openSaved(id: string) { setError(''); try {
    const result = await api<{record: RecordDraft}>(`/api/records/${id}`)
    setText(''); setRecord(result.record); setPending(new Set()); setKept(new Set()); setAck(new Set()); setModelWarnings([]); setSelected(id); setNotice('Opened saved draft. Edits require a new Confirm and save.'); setCompleteness([])
  } catch (e) { fail(e) } }
  async function removeSaved(id: string) { try { await api(`/api/records/${id}`, {method:'DELETE'}); setDeleteId(null); if(selected === id) clear(); await loadRecords(); refresh() } catch(e) { fail(e) } }
  const unresolved = flags.some(f => !kept.has(f.id)) || warnings.some(w => !ack.has(w.message))
  return <>
    <div className="flex flex-wrap items-start justify-between gap-4 mb-7"><div><p className="eyebrow">ENCOUNTER WORKSPACE</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">Make room for the encounter.</h1><p className="text-sm text-slate-500 mt-2">Capture what was said. Review what matters. Save when you're ready.</p></div><span className="bg-white border border-slate-200 rounded-full px-3 py-1.5 text-xs text-slate-500">{demo ? 'Fictional demo' : 'Unsaved text stays in memory'}</span></div>
    <div className="workflow-steps" aria-label="Encounter workflow"><span>01 Capture</span><span>02 Structure</span><span>03 Review</span><span>04 Confirm</span><span>05 Save</span></div>
    {error && <div role="alert" className="error mb-5">{error}</div>}{notice && <div role="status" className="rounded-xl border border-teal-100 bg-teal-50 p-3 text-sm text-teal-800 mb-5">{notice}</div>}
    <div className="encounter-layout grid gap-5 items-start">
      <div className="space-y-5"><section className="panel p-5"><div className="flex items-center justify-between"><p className="eyebrow">01 · CAPTURE</p><FileText size={17} className="text-slate-400"/></div><h2 className="mt-3 text-lg font-semibold">Encounter notes</h2><p className="text-xs leading-relaxed text-slate-500 mt-2 mb-4">Type or dictate. Correct the transcript before structuring; missing facts stay empty.</p><VoiceRecorder key={voiceKey} disabled={!!busy} onTranscript={transcript => setText(prev => prev ? prev + '\n' + transcript : transcript)} onError={fail}/><label htmlFor="encounter" className="sr-only">Encounter text / editable transcript</label><textarea id="encounter" rows={12} value={text} maxLength={30000} onChange={e => setText(e.target.value)} placeholder="Begin with the presentation…"/><div className="flex justify-between text-[10px] text-slate-400 mt-2"><span>LOCAL PROCESSING ONLY</span><span>{text.length.toLocaleString()} / 30,000</span></div><button className="btn-primary w-full mt-5" disabled={!!busy || !text.trim()} onClick={structure}><WandSparkles size={16}/>{busy === 'structure' ? 'Structuring locally…' : 'Structure from text'}</button><p className="text-[11px] text-slate-400 leading-relaxed mt-3">AI can make mistakes. Amber fields require your review.</p></section>
      <section className="panel p-5"><p className="eyebrow mb-4">ENCRYPTED DRAFTS · {saved.length}</p>{!saved.length && <p className="text-xs text-slate-400">Confirmed drafts will appear here.</p>}<div className="space-y-3">{saved.map(item => <div key={item.id} className="border-b border-slate-100 pb-3"><button onClick={() => openSaved(item.id)} className="text-left w-full text-sm font-medium hover:text-teal-700">{item.chief_complaint || 'Encounter draft'}</button><div className="flex justify-between items-center mt-1"><span className="text-[10px] text-slate-400">{new Date(item.timestamp).toLocaleString()}</span><button aria-label="Delete saved record" className="text-slate-400 hover:text-red-700" onClick={() => setDeleteId(item.id)}><Trash2 size={13}/></button></div>{deleteId === item.id && <div className="text-xs mt-2 text-red-800">Delete permanently?<div className="flex gap-3 mt-2"><button onClick={() => removeSaved(item.id)}>Delete</button><button onClick={() => setDeleteId(null)}>Cancel</button></div></div>}</div>)}</div></section></div>
      <section className="panel overflow-hidden"><div className="p-5 border-b border-slate-100 flex justify-between items-start"><div><p className="eyebrow">02 · REVIEW</p><h2 className="mt-3 text-lg font-semibold">Your SOAP draft</h2></div><span className={`text-[10px] font-semibold rounded-full px-2.5 py-1 ${pending.size ? 'bg-amber-50 text-amber-800' : 'bg-teal-50 text-teal-800'}`}>{pending.size ? `${pending.size} to review` : 'All fields editable'}</span></div><div className="p-2"><ReviewForm record={record} pending={pending} warnings={[...warnings, ...modelWarnings]} onConfirm={path => setPending(prev => {const s = new Set(prev); s.delete(path); return s})} onChange={edit}/></div><div className="p-5 border-t border-slate-100 space-y-3"><button className="btn-primary w-full" disabled={!!busy || pending.size > 0 || unresolved} onClick={confirmSave}><Save size={16}/>{busy === 'save' ? 'Encrypting…' : 'Confirm and save'}</button><div className="flex gap-2"><button className="btn flex-1" disabled={!!busy} onClick={clear}><Eraser size={14}/>Clear</button><button className="btn flex-1" disabled={!selected || !!busy} onClick={() => selected && downloadPdf(selected).catch(fail)}><Download size={14}/>Export PDF</button></div><p className="text-[10px] text-slate-400 text-center">Export uses the saved version. Downloaded PDFs are not encrypted.</p></div></section>
      <aside className="space-y-5"><section className="panel p-5"><p className="eyebrow">03 · CHECK</p><h2 className="text-lg font-semibold mt-3">Review flags</h2><p className="text-xs text-slate-500 leading-relaxed mt-2 mb-5">Warning aids, not a guarantee. These checks cannot establish clinical accuracy or de-identification.</p>
      {!warnings.length && !flags.length && !modelWarnings.length && <div className="rounded-xl bg-slate-50 p-4 text-xs text-slate-500 flex gap-2"><Check size={16} className="text-teal-700 flex-shrink-0"/>No numeric or identifier warnings so far.</div>}
      {modelWarnings.map((w, i) => <p key={i} className="text-xs text-amber-800 bg-amber-50 rounded-lg p-3 mb-3">{w.message}</p>)}
      {warnings.map((w, i) => <div key={i} className="rounded-xl bg-amber-50 p-3 mb-3"><div className="text-xs text-amber-900 flex gap-2"><AlertTriangle size={14} className="flex-shrink-0"/>{w.message}</div><label className="text-xs mt-3 flex items-start gap-2 text-amber-900"><input type="checkbox" className="!w-auto mt-0.5" checked={ack.has(w.message)} onChange={e => setAck(prev => {const next = new Set(prev); e.target.checked ? next.add(w.message) : next.delete(w.message); return next})}/>I checked this value against the source.</label></div>)}
      {flags.map(flag => <div key={flag.id} className="rounded-xl bg-rose-50 p-3 mb-3 text-xs"><p className="font-semibold text-rose-900">{flag.kind}</p><p className="break-all mt-1 text-rose-800">{flag.text}</p><p className="text-[10px] text-slate-500 mt-1">{flag.field}</p><div className="flex gap-3 mt-3"><button className="text-rose-800 font-semibold" onClick={() => removeFlag(flag)}>Remove (recommended)</button><button className="text-slate-600" onClick={() => setKept(prev => {const next = new Set(prev); next.has(flag.id) ? next.delete(flag.id) : next.add(flag.id); return next})}>{kept.has(flag.id) ? 'Kept ✓' : 'Keep'}</button></div></div>)}
      <div className="mt-5 border-t border-slate-100 pt-5"><button className="btn w-full" disabled={!!busy} onClick={check}><ClipboardCheck size={15}/>{busy === 'check' ? 'Checking local library…' : 'Check completeness'}</button><p className="text-[10px] text-slate-400 mt-2">Compares documentation with your notes and guidelines.</p>{checkMessage && <p className="text-xs text-slate-600 mt-3">{checkMessage}</p>}{completeness.map((flag, i) => <div key={i} className="mt-3 rounded-lg bg-teal-50 p-3"><p className="text-xs text-teal-900">{flag.item}</p><button className="text-[10px] text-teal-700 underline mt-2" onClick={() => setCitation(flag.citation)}>{flag.citation.filename}, {flag.citation.location_type === 'section' ? 'section' : 'p.'} {flag.citation.page}</button></div>)}</div></section><div className="px-2 text-xs text-slate-400 leading-relaxed">The assistant extracts and checks documentation. It does not diagnose, recommend treatment, or replace your supervisor.</div></aside>
    </div>{citation && <CitationView citation={citation} onClose={() => setCitation(null)}/>}
  </>
}
