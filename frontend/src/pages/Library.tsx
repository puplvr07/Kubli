import { useEffect, useRef, useState } from 'react'
import { Upload, BookOpen, Trash2, RefreshCw, FileText, X, FlaskConical, Check, AlertTriangle } from 'lucide-react'
import { api, post } from '../api'
import type { LibraryDocument, DeidFlag } from '../types'
type Review = { filename: string; flags: DeidFlag[]; pages: number; chunks: number }
const tagNames: {[key:string]:string} = {notes:'My notes', guidelines:'Guideline', textbook:'Textbook'}
export default function Library({refresh, demo}: {refresh: () => void; demo: boolean}) {
  const [documents, setDocuments] = useState<LibraryDocument[]>([]); const [files, setFiles] = useState<File[]>([])
  const [tag, setTag] = useState('notes'); const [ocr, setOcr] = useState(false); const [reviews, setReviews] = useState<Review[]>([])
  const [excluded, setExcluded] = useState(new Set<string>()); const [approved, setApproved] = useState(new Set<string>())
  const [busy, setBusy] = useState(''); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const [deleteId, setDeleteId] = useState<string | null>(null); const [progress, setProgress] = useState({done:0,total:0})
  const input = useRef<HTMLInputElement>(null)
  async function load() { try { setDocuments(await api<LibraryDocument[]>('/api/library')); refresh() } catch(e) { setError((e as Error).message) } }
  useEffect(() => { void load() }, [])
  function reset() { setFiles([]); setReviews([]); setExcluded(new Set()); setApproved(new Set()); if(input.current) input.current.value = '' }
  function form(selected: File[], proceed = false) {
    const data = new FormData(); selected.forEach(file => data.append('files', file)); data.append('tag',tag); data.append('ocr',String(ocr)); data.append('proceed',String(proceed))
    data.append('deid_keep',JSON.stringify(Object.fromEntries(reviews.map(review => [review.filename,review.flags.filter(flag => approved.has(flag.id)).map(flag => flag.id)]))))
    return data
  }
  async function scan() {
    setBusy('Scanning identifiers and extracting text locally…'); setError(''); setNotice('')
    try {
      if (new Set(files.map(file => file.name)).size !== files.length) throw new Error('Choose files with distinct filenames so citation sources remain clear.')
      const result = await api<{files: Review[]}>('/api/library/upload', {method:'POST',body:form(files)})
      setReviews(result.files); setExcluded(new Set()); setApproved(new Set()); setNotice('Review these files before indexing. Nothing has been saved yet.')
    } catch(e) {setError((e as Error).message)} finally {setBusy('')}
  }
  async function index() {
    const included = files.filter(file => !excluded.has(file.name)); setError(''); setNotice(''); setProgress({done:0,total:included.length})
    try {
      for (let i=0;i<included.length;i++) {
        setBusy(`Embedding and encrypting ${included[i].name} locally (${i+1}/${included.length})…`)
        await api('/api/library/upload', {method:'POST',body:form([included[i]],true)})
        setProgress({done:i+1,total:included.length})
        await load()
      }
      reset(); setNotice(`${included.length} file${included.length === 1 ? '' : 's'} indexed and encrypted locally.`)
    } catch(e) {setError((e as Error).message + ' Completed files remain in your library; exclude them before retrying.'); await load() } finally {setBusy('')}
  }
  async function samples() {
    setBusy('Embedding and encrypting sample library locally…'); setError('')
    try {await post('/api/demo/library',{}); await load(); setNotice('Sample library is ready. All sample files are invented demonstration checklists, not real clinical guidance.')} catch(e) {setError((e as Error).message)} finally {setBusy('')}
  }
  async function reindex() {setBusy('Rebuilding local embeddings; old index is retained until success…');setError('');try{const result=await post<{chunks_indexed:number}>('/api/library/reindex',{});setNotice(`${result.chunks_indexed} chunks reindexed locally.`);await load()}catch(e){setError((e as Error).message)}finally{setBusy('')}}
  async function remove(id:string) {setError('');try{await api(`/api/library/${id}`,{method:'DELETE'});setDeleteId(null);await load()}catch(e){setError((e as Error).message)}}
  const includedReviews = reviews.filter(review => !excluded.has(review.filename))
  const ready = includedReviews.length > 0 && includedReviews.every(review => review.flags.every(flag => approved.has(flag.id)))
  return <><div className="flex flex-wrap justify-between gap-4 mb-7"><div><p className="eyebrow">YOUR LOCAL SOURCES</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">A library that stays with you.</h1><p className="text-sm text-slate-500 mt-2">Your notes, textbooks, and guidelines. Encrypted on this device.</p></div><button className="btn self-start" disabled={!!busy} onClick={reindex}><RefreshCw size={15}/>Reindex library</button></div>
    {error && <p role="alert" className="error mb-5">{error}</p>}{notice && <p role="status" className="rounded-xl bg-teal-50 border border-teal-100 p-4 text-sm text-teal-800 mb-5">{notice}</p>}
    <div className="grid gap-6 xl:grid-cols-[1fr_1.5fr]"><section className="panel p-6 self-start"><p className="eyebrow">ADD MATERIAL</p><h2 className="text-lg font-semibold mt-3">Import your sources</h2><div className="relative rounded-xl border border-dashed border-slate-300 bg-slate-50 py-8 px-5 my-5 text-center"><Upload className="mx-auto text-teal-700 mb-3" size={24}/><label htmlFor="uploads" className="text-sm font-medium cursor-pointer">Choose local files</label><input ref={input} id="uploads" type="file" className="mt-4 !text-xs" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" multiple disabled={!!busy || !!reviews.length} onChange={e => {setFiles(Array.from(e.target.files ?? []));setNotice('');setError('')}}/><p className="text-xs text-slate-400 mt-3">PDF, DOCX, TXT, MD · PNG/JPG with local OCR<br/>20 MB per file · 10 files · 30 MB combined</p></div><div className="space-y-4"><div><label htmlFor="tag" className="field-label">Source type</label><select id="tag" className="mt-2" value={tag} disabled={!!busy || !!reviews.length} onChange={e=>setTag(e.target.value)}>{Object.entries(tagNames).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></div><label className="flex items-start gap-2 text-xs text-slate-600"><input type="checkbox" className="!w-auto mt-0.5" checked={ocr} disabled={!!busy || !!reviews.length} onChange={e=>setOcr(e.target.checked)}/>Use local OCR for images / scanned PDF pages (best effort)</label><p className="text-[11px] text-slate-400">OCR can miss or misread text and numbers. Check the source before using any excerpt.</p></div>
    {!reviews.length ? <button className="btn-primary w-full mt-5" disabled={!!busy || !files.length} onClick={scan}><ShieldIcon/>Review files before indexing</button> : <div className="mt-5 space-y-3"><button className="btn-primary w-full" disabled={!!busy || !ready} onClick={index}><Check size={16}/>Proceed and index {includedReviews.length} files</button><button className="btn w-full" disabled={!!busy} onClick={()=>{reset();setNotice('Import canceled. Unindexed files were not saved.')}}><X size={15}/>Cancel import</button></div>}
    {busy && <div role="status" aria-live="polite" className="mt-5 text-xs text-teal-800"><p>{busy}</p><progress aria-label="Local indexing progress" className="w-full mt-3 accent-teal-700" {...(progress.total && busy.startsWith('Embedding and encrypting ') ? {value:progress.done,max:progress.total} : {})}/><p className="text-[10px] text-slate-400 mt-2">Processing runs on your local CPU. Large files can take a while.</p></div>}
    <div className="mt-6 border-t border-slate-100 pt-5"><button className="btn-soft w-full" disabled={!!busy} onClick={samples}><FlaskConical size={16}/>{demo ? 'Load / refresh demo library' : 'Load sample library'}</button><p className="text-[10px] text-slate-400 mt-2 leading-relaxed">Three example checklists and one notes file. SAMPLE ONLY, not real clinical guidance.</p></div></section>
    <div className="space-y-6">{reviews.length > 0 && <section className="panel p-6"><h2 className="text-lg font-semibold flex gap-2 items-center"><AlertTriangle size={19} className="text-amber-600"/>De-identification review</h2><p className="text-xs text-slate-500 mt-2 mb-5">Warning aid only, not a guarantee. Cancel or exclude a file if identifiers should not be retained.</p>{reviews.map(review=><div key={review.filename} className="border-t border-slate-100 py-4"><div className="flex justify-between items-start gap-3"><div><p className="text-sm font-semibold break-all">{review.filename}</p><p className="text-xs text-slate-400 mt-1">{review.pages} pages / sections · {review.chunks} chunks</p></div><label className="text-xs flex gap-2 whitespace-nowrap"><input type="checkbox" className="!w-auto" checked={excluded.has(review.filename)} onChange={e=>setExcluded(prev=>{const s=new Set(prev);e.target.checked?s.add(review.filename):s.delete(review.filename);return s})}/>Exclude file</label></div>{!excluded.has(review.filename) && <>{!review.flags.length && <p className="text-xs text-teal-700 mt-3">No identifiers flagged. Review the original file too.</p>}{review.flags.map(flag=><label key={flag.id} className="flex items-start gap-3 mt-3 rounded-lg bg-amber-50 p-3 text-xs"><input type="checkbox" className="!w-auto mt-0.5" checked={approved.has(flag.id)} onChange={e=>setApproved(prev=>{const s=new Set(prev);e.target.checked?s.add(flag.id):s.delete(flag.id);return s})}/><span><span className="font-semibold text-amber-900">Keep this flagged text: </span><span className="break-all">{flag.text}</span><span className="block text-amber-800 mt-1">{flag.kind} · {flag.field}</span></span></label>)}</>}</div>)}</section>}
    <section className="panel overflow-hidden"><div className="p-6 flex items-center justify-between border-b border-slate-100"><div><p className="eyebrow">INDEXED ON THIS DEVICE</p><h2 className="text-lg font-semibold mt-2">Your sources <span className="text-slate-400 font-normal">{documents.length}</span></h2></div><BookOpen size={22} className="text-slate-400"/></div>{!documents.length ? <div className="text-center py-16 px-5"><FileText size={30} className="mx-auto text-slate-300 mb-4"/><p className="text-sm text-slate-500">Give your questions a source.</p><p className="text-xs text-slate-400 mt-2">Import a file or load the sample library to begin.</p></div> : <div>{documents.map(document=><div key={document.id} className="p-5 border-b border-slate-100 last:border-0 flex gap-4 items-start"><div className="w-10 h-10 rounded-lg bg-slate-50 text-teal-700 shrink-0 grid place-items-center"><FileText size={19}/></div><div className="flex-1 min-w-0"><p className="text-sm font-semibold break-all">{document.title}</p><div className="flex flex-wrap gap-2 items-center mt-2 text-[10px]"><span className="rounded bg-teal-50 text-teal-800 px-2 py-1">{tagNames[document.tag]}</span><span className="text-slate-400">{document.chunks} chunks · {new Date(document.timestamp).toLocaleDateString()}</span>{document.sample && <span className="text-amber-700">SAMPLE ONLY</span>}</div>{deleteId===document.id && <div className="text-xs text-red-800 mt-3">Delete this source and every encrypted chunk?<div className="flex gap-4 mt-2"><button onClick={()=>remove(document.id)}>Delete permanently</button><button onClick={()=>setDeleteId(null)}>Cancel</button></div></div>}</div><button className="text-slate-400 hover:text-red-800" aria-label={`Delete ${document.title}`} disabled={!!busy} onClick={()=>setDeleteId(document.id)}><Trash2 size={16}/></button></div>)}</div>}</section><p className="text-xs text-slate-400 px-2 leading-relaxed">Original uploads are not retained. Extracted text, filenames, tags, and embeddings are encrypted. PDFs retain real page numbers; DOCX citations refer to sections.</p></div></div>
  </>
}
function ShieldIcon(){return <BookOpen size={16}/>}
