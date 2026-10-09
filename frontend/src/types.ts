export interface RecordDraft {
  patient: { age: number | null; sex: string | null }
  chief_complaint: string | null; hpi: string | null; past_history: string | null
  medications: string[]; allergies: string[]
  vitals: { bp: string | null; hr: number | null; rr: number | null; temp_c: number | null; spo2: number | null }
  physical_exam: string | null; assessment: string | null; plan: string | null
}
export interface Warning { field: string; message: string }
export interface DeidFlag { id: string; kind: string; text: string; start: number; end: number; field?: string }
export interface Citation { chunk_id: string; filename: string; page: number; heading: string; location_type?: string; snippet: string; context: string }
export interface LibraryDocument { id: string; title: string; tag: string; timestamp: string; chunks: number; sample: boolean }
export interface SavedRecord { id: string; timestamp: string; chief_complaint: string | null }
export interface Status {
  initialized: boolean; unlocked: boolean; auto_lock_minutes: number
  backend_bind: string; outbound_policy: string; external_requests: number
  local_model_requests: number; llm_model: string; embedding_model: string; whisper_model: string
  documents: number | null; chunks: number | null; model_status?: string
}
export const blankRecord = (): RecordDraft => ({ patient: { age: null, sex: null }, chief_complaint: null, hpi: null, past_history: null, medications: [], allergies: [], vitals: { bp: null, hr: null, rr: null, temp_c: null, spo2: null }, physical_exam: null, assessment: null, plan: null })
