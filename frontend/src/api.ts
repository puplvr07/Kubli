const BASE = 'http://127.0.0.1:8000'
let session: string | null = null
let onLocked: () => void = () => {}
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) { super(message) }
}
export function setSession(token: string | null) { session = token }
export function setLockHandler(handler: () => void) { onLocked = handler }
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (session) headers.set('Authorization', `Bearer ${session}`)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let response: Response
  try { response = await fetch(`${BASE}${path}`, { ...options, headers, cache: 'no-store', credentials: 'omit', redirect: 'error' }) }
  catch { throw new Error('Local backend is unavailable. Run: python -m app.main (from backend with the virtual environment activated).') }
  if (!response.ok) {
    if (response.status === 401 && !path.includes('unlock')) { session = null; onLocked() }
    const data = await response.json().catch(() => ({}))
    throw new ApiError(typeof data.detail === 'string' ? data.detail : 'Request could not be completed. Check your fields and retry.',
      response.status, typeof data.status === 'string' ? data.status : undefined)
  }
  return response.json() as Promise<T>
}
export function post<T>(path: string, body: unknown): Promise<T> { return api<T>(path, { method: 'POST', body: JSON.stringify(body) }) }
export async function downloadPdf(id: string) {
  const response = await fetch(`${BASE}/api/records/${encodeURIComponent(id)}/pdf`, { headers: session ? { Authorization: `Bearer ${session}` } : {}, cache: 'no-store', redirect: 'error' })
  if (!response.ok) {
    if (response.status === 401) { session = null; onLocked() }
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : 'PDF export failed. Unlock the vault and retry.')
  }
  const url = URL.createObjectURL(await response.blob()); const a = document.createElement('a')
  a.href = url; a.download = `wardnote-${id.slice(0, 8)}.pdf`; a.click(); URL.revokeObjectURL(url)
}
