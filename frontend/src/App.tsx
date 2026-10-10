import { useCallback, useEffect, useRef, useState } from 'react'
import { ShieldCheck, LockKeyhole, FileText, Library as LibraryIcon, MessageSquareText, FlaskConical } from 'lucide-react'
import { BrandMark, Wordmark } from './components/Brand'
import { api, post, setSession, setLockHandler } from './api'
import type { Status } from './types'
import Lock from './pages/Lock'
import Main from './pages/Main'
import Library from './pages/Library'
import Ask from './pages/Ask'
import OfflineProof from './components/OfflineProof'
type Page = 'main' | 'library' | 'ask'
export default function App() {
  const [token, setToken] = useState<string | null>(null); const [status, setStatus] = useState<Status | null>(null)
  const [demoBusy, setDemoBusy] = useState(false)
  const [page, setPage] = useState<Page>('main'); const [demo, setDemo] = useState(false); const [error, setError] = useState('')
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const clearSession = useCallback(() => { setSession(null); setToken(null); setDemo(false); setPage('main'); setStatus(prev => prev ? {...prev, initialized: true, unlocked: false, documents: null, chunks: null} : null) }, [])
  const refresh = useCallback(() => { api<Status>('/api/status').then(setStatus).catch(e => setError(e.message)) }, [])
  useEffect(() => { setLockHandler(clearSession); refresh(); return () => setLockHandler(() => {}) }, [clearSession, refresh])
  const lock = useCallback(() => { void post('/api/lock', {}).catch(() => {}); clearSession() }, [clearSession])
  useEffect(() => {
    if (!token) return
    let lastTouch = 0
    function activity() {
      clearTimeout(timeout.current); timeout.current = setTimeout(lock, (status?.auto_lock_minutes ?? 5) * 60000)
      if (Date.now() - lastTouch > Math.min(15000, (status?.auto_lock_minutes ?? 5) * 20000)) { lastTouch = Date.now(); void post('/api/session/touch', {}).catch(() => {}) }
    }
    activity()
    const events = ['pointerdown', 'keydown', 'scroll', 'touchstart'] as const
    events.forEach(event => window.addEventListener(event, activity, {passive: true}))
    return () => { clearTimeout(timeout.current); events.forEach(event => window.removeEventListener(event, activity)) }
  }, [token, lock, status?.auto_lock_minutes])
  async function toggleDemo(value: boolean) {
    setDemo(value); setPage('main'); setError('')
    if (value) { setDemoBusy(true); try { await post('/api/demo/library', {}); refresh() } catch (e) { setError('Demo presentation loaded. Sample library: ' + (e as Error).message) } finally { setDemoBusy(false) } }
  }
  function unlock(value: string) { setSession(value); setToken(value); setError(''); refresh() }
  const nav: {id: Page; label: string; icon: typeof FileText}[] = [{id:'main', label:'Patient encounter', icon:FileText}, {id:'library',label:'My library',icon:LibraryIcon}, {id:'ask',label:'Ask your sources',icon:MessageSquareText}]
  return <div className="app-frame min-h-screen flex flex-col pb-12"><header className="app-header sticky top-0 z-40 h-[76px] px-5 lg:px-9 flex items-center justify-between gap-4"><div className="flex items-center gap-3"><BrandMark className="w-10 h-10 text-[#10211F]"/><Wordmark/><span className="hidden sm:inline text-[10px] text-[#668078] border-l border-[#cfddd5] pl-4 ml-2 tracking-[.16em]">PRIVATE STUDY WORKSPACE</span></div><div className="flex gap-5 items-center"><span className="hidden sm:flex items-center gap-2 text-xs text-teal-800"><span className="w-1.5 h-1.5 bg-[#3b9c72] rounded-full"/>On-device only</span>{token && <button className="btn !py-2 !text-xs" onClick={lock}><LockKeyhole size={14}/>Lock vault</button>}</div></header>
    {token ? <div className="flex-1 flex flex-col lg:flex-row" key={token}><aside className="lg:sticky lg:top-[76px] lg:h-[calc(100vh-124px)] lg:w-[225px] shrink-0 border-b lg:border-b-0 lg:border-r border-slate-200 bg-[#eef3f0] p-5 lg:p-6 flex lg:flex-col gap-5"><div className="flex-1"><p className="eyebrow hidden lg:block mb-5 mt-2">WORKSPACE</p><nav aria-label="Workspace navigation" className="flex lg:flex-col gap-2 overflow-auto">{nav.map(({id,label,icon: Icon}) => <button key={id} aria-current={page === id ? 'page' : undefined} onClick={() => {setPage(id); refresh()}} className={`flex items-center gap-3 rounded-lg px-3 py-3 text-xs whitespace-nowrap text-left ${page===id ? 'bg-white shadow-sm text-teal-900 font-semibold' : 'text-slate-500 hover:bg-white/60'}`}><Icon size={17}/>{label}</button>)}</nav></div><div className="hidden lg:block"><div className="rounded-xl p-4 border border-slate-200 bg-white/60 mb-4"><div className="flex items-center justify-between gap-3"><label htmlFor="demo" className="text-xs font-semibold flex gap-2 items-center"><FlaskConical size={15}/>Demo mode</label><input id="demo" type="checkbox" className="!w-auto accent-teal-800" checked={demo} disabled={demoBusy} onChange={e => void toggleDemo(e.target.checked)}/></div><p className="text-[10px] text-slate-500 mt-3 leading-relaxed">Loads a fictional presentation and indexes the SAMPLE ONLY library locally.</p></div><OfflineProof status={status}/><p className="text-[10px] text-slate-400 mt-5 flex items-center gap-2"><ShieldCheck size={12}/>AES-256-GCM local vault</p></div></aside><main className="flex-1 min-w-0 p-5 lg:p-8">{error && <p role="alert" className="error mb-5">{error}</p>}{demoBusy && <p role="status" className="text-xs text-teal-800 mb-4">Indexing the sample library with local embeddings…</p>}<div className="lg:hidden mb-4 flex items-center justify-between"><label className="text-xs flex gap-2"><input type="checkbox" className="!w-auto" checked={demo} disabled={demoBusy} onChange={e => void toggleDemo(e.target.checked)}/>Demo mode</label><div className="w-48"><OfflineProof status={status}/></div></div><div hidden={page !== 'main'}><Main demo={demo} refresh={refresh}/></div>{page === 'library' && <Library demo={demo} refresh={refresh}/>} {page === 'ask' && <Ask/>}</main></div> : <main className="flex-1 px-6 lg:px-10"><Lock initialized={status?.initialized ?? false} onUnlock={unlock}/>{error && <div className="max-w-lg mx-auto mb-6"><p role="alert" className="error">{error}</p><button className="btn mt-3" onClick={refresh}>Retry local backend</button></div>}</main>}
    <footer className="fixed bottom-0 left-0 right-0 z-40 border-t border-slate-200 bg-white px-5 py-4 text-center text-[11px] text-slate-500">Draft-support tool. Not a diagnostic tool and not the official medical record.</footer>
  </div>
}
