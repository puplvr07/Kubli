from io import BytesIO
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from html import escape
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import Paragraph
from reportlab.pdfgen import canvas
from app.schemas import Record

FONT_DIR = Path(__file__).resolve().parents[3] / 'frontend' / 'public' / 'fonts'
pdfmetrics.registerFont(TTFont('WardSans', str(FONT_DIR / 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('WardSans-Bold', str(FONT_DIR / 'DejaVuSans-Bold.ttf')))

DISCLAIMER = 'Draft-support tool. Not a diagnostic tool and not the official medical record.'


def render_pdf(saved: dict) -> bytes:
    """One page; oversized drafts fail explicitly instead of silently truncating."""
    record = Record.model_validate(saved['record'])
    data = record.model_dump()
    sections = [
        ('PATIENT', f'Age: {data["patient"]["age"] if data["patient"]["age"] is not None else "Not stated"} · Sex: {data["patient"]["sex"] or "Not stated"}'),
        ('S · SUBJECTIVE', '\n'.join([
            'Chief complaint: ' + (data['chief_complaint'] or 'Not stated'),
            'HPI: ' + (data['hpi'] or 'Not stated'), 'Past history: ' + (data['past_history'] or 'Not stated'),
            'Medications: ' + ('; '.join(data['medications']) or 'Not stated'), 'Allergies: ' + ('; '.join(data['allergies']) or 'Not stated')])),
        ('O · OBJECTIVE', 'Vitals: ' + '; '.join(f'{k}: {v if v is not None else "Not stated"}' for k, v in data['vitals'].items()) + '\nPhysical exam: ' + (data['physical_exam'] or 'Not stated')),
        ('A · ASSESSMENT AS STATED', data['assessment'] or 'Not stated'),
        ('P · PLAN AS STATED', data['plan'] or 'Not stated'),
    ]
    glyphs = pdfmetrics.getFont('WardSans').face.charToGlyph
    if any(ord(char) not in glyphs for _, body in sections for char in body if char not in '\n\r\t'):
        from fastapi import HTTPException
        raise HTTPException(422, 'The bundled PDF font does not support some characters in this draft. Export was stopped to avoid losing text.')
    width, height = 595.28, 841.89
    selected = None
    for size in (10, 9, 8):
        style = ParagraphStyle('body', fontName='WardSans', fontSize=size, leading=size * 1.35, textColor=colors.HexColor('#243b39'), alignment=TA_LEFT)
        laid_out = [(title, Paragraph(escape(body).replace('\n', '<br/>'), style)) for title, body in sections]
        required = sum(p.wrap(width - 88, height)[1] + 34 for _, p in laid_out)
        if required <= 615:
            selected = laid_out
            break
    if selected is None:
        from fastapi import HTTPException
        raise HTTPException(422, 'This draft is too long for a readable one-page PDF. Shorten the reviewed draft; no content was truncated.')
    output = BytesIO()
    page = canvas.Canvas(output, pagesize=(width, height))
    page.setTitle('WardNote encounter draft')
    page.setAuthor('WardNote · local draft support')
    page.setFillColor(colors.HexColor('#115e59'))
    page.setFont('WardSans-Bold', 23)
    page.drawString(44, 790, 'WardNote')
    page.setFont('WardSans', 10)
    page.drawString(44, 771, 'ENCOUNTER DRAFT · FOR REVIEW / STUDY')
    page.setFillColor(colors.HexColor('#64748b'))
    page.setFont('WardSans', 8)
    page.drawString(44, 750, 'Saved: ' + saved['timestamp'])
    page.drawString(44, 737, 'Generated: ' + datetime.now(timezone.utc).isoformat(timespec='seconds'))
    y = 711
    for title, paragraph in selected:
        page.setFont('WardSans-Bold', 9)
        page.setFillColor(colors.HexColor('#115e59'))
        page.drawString(44, y, title)
        _, h = paragraph.wrap(width - 88, height)
        paragraph.drawOn(page, 44, y - 12 - h)
        y -= h + 34
    page.setStrokeColor(colors.HexColor('#dbe3df'))
    page.line(44, 55, width - 44, 55)
    page.setFont('WardSans', 7)
    page.setFillColor(colors.HexColor('#64748b'))
    page.drawString(44, 40, DISCLAIMER)
    page.showPage()
    page.save()
    return output.getvalue()
