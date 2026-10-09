from pathlib import Path
from fastapi import APIRouter, Depends
from app.dependencies import unlocked
from app.schemas import empty_record
from app.services.parsing import parse_file
from app.routers.library import prepare_document, document_summary

router = APIRouter(prefix='/api/demo')

@router.post('/presentation')
def presentation(vault=Depends(unlocked)):
    text = ('28-year-old female reports chest pain for two hours, worse with movement. '
            'Past history: not stated. Medications: not stated. Allergies: not stated.\n'
            'BP 118/76, HR 88, RR 18, temperature 36.8 C, SpO2 98%.\n'
            'Physical exam: alert, speaking in full sentences.\n'
            'Assessment: chest pain, cause not stated.\n'
            'Plan: present findings to the supervising clinician.')
    record = empty_record()
    record.patient.age = 28; record.patient.sex = 'female'
    record.chief_complaint = 'chest pain'
    record.hpi = 'chest pain for two hours, worse with movement'
    record.vitals.bp = '118/76'; record.vitals.hr = 88; record.vitals.rr = 18; record.vitals.temp_c = 36.8; record.vitals.spo2 = 98
    record.physical_exam = 'alert, speaking in full sentences'
    record.assessment = 'chest pain, cause not stated.'
    record.plan = 'present findings to the supervising clinician.'
    return {'text': text, 'record': record.model_dump(), 'prewritten': True}

@router.post('/library')
async def samples(vault=Depends(unlocked)):
    token = vault.token
    directory = Path(__file__).resolve().parents[3] / 'guidelines'
    existing = {d['title'] for d in vault.list('document') if d['sample']}
    items = []; chunks = []; documents = []
    for path in sorted(directory.iterdir()):
        if path.name in existing or path.suffix not in ('.txt', '.md'):
            continue
        document, pieces = await prepare_document(path.name, parse_file(path.name, path.read_bytes()), 'notes' if path.suffix == '.md' else 'guidelines', sample=True, vault=vault, token=token)
        documents.append(document); items.append(('document', document)); items.extend(('chunk', piece) for piece in pieces); chunks.extend(pieces)
    vault.authorize(token, touch=False)
    vault.put_many(items); vault.index.extend(chunks)
    return {'documents': [document_summary(d) for d in documents], 'chunks_indexed': len(chunks)}
