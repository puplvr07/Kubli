import type { RecordDraft, Warning } from '../types'
export const fields = [
  ['patient.age', 'Age (years)', 'number'], ['patient.sex', 'Sex as stated', 'text'],
  ['chief_complaint', 'Chief complaint', 'text'], ['hpi', 'History of present illness', 'area'],
  ['past_history', 'Past history', 'area'], ['medications', 'Medications · one per line', 'list'],
  ['allergies', 'Allergies · one per line', 'list'], ['vitals.bp', 'BP (mmHg)', 'text'],
  ['vitals.hr', 'Heart rate (bpm)', 'number'], ['vitals.rr', 'Resp. rate (/min)', 'number'],
  ['vitals.temp_c', 'Temperature (°C)', 'number'], ['vitals.spo2', 'SpO₂ (%)', 'number'],
  ['physical_exam', 'Physical examination', 'area'], ['assessment', 'Assessment as stated', 'area'], ['plan', 'Plan as stated', 'area'],
] as const
export function valueAt(record: RecordDraft, path: string): string {
  const [a, b] = path.split('.')
  const top = record[a as keyof RecordDraft]
  const value = b ? (top as unknown as { [key: string]: unknown })[b] : top
  return Array.isArray(value) ? value.join('\n') : value === null ? '' : String(value)
}
export function updateAt(record: RecordDraft, path: string, raw: string, kind: string): RecordDraft {
  const result = structuredClone(record)
  const value = kind === 'list' ? raw.split('\n').filter(x => x.trim()) : raw === '' ? null : kind === 'number' ? Number(raw) : raw
  const [a, b] = path.split('.')
  if (b) (result[a as keyof RecordDraft] as unknown as { [key: string]: unknown })[b] = value
  else (result as unknown as { [key: string]: unknown })[a] = value
  return result
}
const groups = [
  { title: 'Patient details', note: 'As stated in the encounter', paths: ['patient.age', 'patient.sex'], className: 'review-group-patient' },
  { title: 'Subjective', note: 'Reported history and symptoms', paths: ['chief_complaint', 'hpi', 'past_history', 'medications', 'allergies'], className: 'review-group-subjective' },
  { title: 'Objective', note: 'Measured and observed findings', paths: ['vitals.bp', 'vitals.hr', 'vitals.rr', 'vitals.temp_c', 'vitals.spo2', 'physical_exam'], className: 'review-group-objective' },
  { title: 'Assessment', note: 'Only what was explicitly stated', paths: ['assessment'], className: 'review-group-assessment' },
  { title: 'Plan', note: 'Only what was explicitly stated', paths: ['plan'], className: 'review-group-plan' },
]
export default function ReviewForm({ record, onChange, pending, onConfirm, warnings }: {
  record: RecordDraft; onChange: (record: RecordDraft, path: string) => void; pending: Set<string>
  onConfirm: (path: string) => void; warnings: Warning[]
}) {
  function renderField([path, label, kind]: (typeof fields)[number]) {
    const highlighted = pending.has(path)
    return <div key={path} className={highlighted ? 'review-field ai-field' : 'review-field'}>
      <div className="flex items-center justify-between gap-2 mb-2"><label htmlFor={path} className="field-label">{label}</label>
        {highlighted && <button type="button" className="text-xs font-semibold text-teal-700" onClick={() => onConfirm(path)}>Review ✓</button>}</div>
      {kind === 'area' || kind === 'list' ? <textarea id={path} rows={kind === 'area' ? 3 : 2} value={valueAt(record, path)} placeholder="Not stated" onChange={e => onChange(updateAt(record, path, e.target.value, kind), path)} />
        : <input id={path} type={kind === 'number' ? 'number' : 'text'} step="any" value={valueAt(record, path)} placeholder="Not stated" onChange={e => onChange(updateAt(record, path, e.target.value, kind), path)} />}
      {warnings.filter(w => w.field === path).map((w, i) => <p key={i} className="mt-2 text-xs text-amber-800">{w.message}</p>)}
    </div>
  }
  return <div className="review-groups">{groups.map(group => <section key={group.title} className={`review-group ${group.className}`} aria-label={group.title}>
    <div className="review-group-heading"><h3>{group.title}</h3><p>{group.note}</p></div>
    <div className="review-group-fields">{fields.filter(([path]) => group.paths.includes(path)).map(renderField)}</div>
  </section>)}</div>
}
