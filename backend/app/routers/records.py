from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Response
from app.schemas import SaveInput, DeidInput, Record
from app.services.deid import scan, scan_record
from app.services.numeric import validate_record
from app.services.pdf import render_pdf
from app.dependencies import unlocked

router = APIRouter(prefix='/api')

@router.post('/deid')
def deid(body: DeidInput, vault=Depends(unlocked)):
    return {'flags': scan(body.text), 'notice': 'Warning aid only; not a guarantee of de-identification.'}

@router.post('/review')
def review(record: Record, vault=Depends(unlocked)):
    return {'flags': scan_record(record), 'warnings': validate_record(record)}

@router.post('/records', status_code=201)
def save_record(body: SaveInput, vault=Depends(unlocked)):
    flags = scan_record(body.record)
    if any(flag['id'] not in body.deid_keep for flag in flags):
        raise HTTPException(409, 'Review identifiers before saving. Remove them or explicitly choose Keep for every flagged item.')
    warnings = validate_record(body.record)
    if any(w.message not in body.warning_acknowledgements for w in warnings):
        raise HTTPException(409, 'Confirm each numeric warning before saving.')
    item = {'id': str(uuid4()), 'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'chief_complaint': body.record.chief_complaint, 'record': body.record.model_dump(),
            'reviewed_warnings': [w.model_dump() for w in warnings], 'kept_identifiers': [f['kind'] for f in flags]}
    vault.put_many([('record', item)])
    return {'id': item['id'], 'timestamp': item['timestamp']}

@router.get('/records')
def list_records(vault=Depends(unlocked)):
    return sorted([{'id': r['id'], 'timestamp': r['timestamp'], 'chief_complaint': r['chief_complaint']} for r in vault.list('record')], key=lambda r: r['timestamp'], reverse=True)

@router.get('/records/{item_id}')
def get_record(item_id: str, vault=Depends(unlocked)):
    return vault.get('record', item_id)

@router.delete('/records/{item_id}')
def delete_record(item_id: str, vault=Depends(unlocked)):
    vault.delete('record', item_id)
    return {'deleted': True}

@router.get('/records/{item_id}/pdf')
def pdf(item_id: str, vault=Depends(unlocked)):
    content = render_pdf(vault.get('record', item_id))
    return Response(content, media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="wardnote-draft.pdf"', 'Cache-Control': 'no-store'})
