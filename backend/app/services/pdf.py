"""Print friendly export of a reviewed encounter draft."""
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from app.schemas import Record

FONT_DIR = Path(__file__).resolve().parents[3] / 'frontend' / 'public' / 'fonts'
pdfmetrics.registerFont(TTFont('TiboqSans', str(FONT_DIR / 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('TiboqSans-Bold', str(FONT_DIR / 'DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('TiboqSans', normal='TiboqSans', bold='TiboqSans-Bold')

DISCLAIMER = 'Draft-support tool. Not a diagnostic tool and not the official medical record.'
FOREST = colors.HexColor('#14564e')
INK = colors.HexColor('#203b36')
MUTED = colors.HexColor('#526960')
MINT = colors.HexColor('#e8f4ee')
RULE = colors.HexColor('#d4e4da')


def _value(value) -> str:
    if value is None or value == '' or value == []:
        return 'Not stated'
    if isinstance(value, list):
        return '; '.join(str(item) for item in value)
    return str(value)


def render_pdf(saved: dict) -> bytes:
    """Render every record field; reject drafts that cannot fit legibly."""
    data = Record.model_validate(saved['record']).model_dump()
    patient, vitals = data['patient'], data['vitals']
    sections = [
        ('PATIENT', [('Age', patient['age']), ('Sex', patient['sex'])]),
        ('S  /  SUBJECTIVE', [
            ('Chief complaint', data['chief_complaint']), ('History of present illness', data['hpi']),
            ('Past history', data['past_history']), ('Medications', data['medications']),
            ('Allergies', data['allergies'])]),
        ('O  /  OBJECTIVE', [
            ('Blood pressure', vitals['bp']), ('Heart rate', vitals['hr']),
            ('Respiratory rate', vitals['rr']), ('Temperature (°C)', vitals['temp_c']),
            ('Oxygen saturation (%)', vitals['spo2']), ('Physical exam', data['physical_exam'])]),
        ('A  /  ASSESSMENT AS STATED', [('Assessment', data['assessment'])]),
        ('P  /  PLAN AS STATED', [('Plan', data['plan'])]),
    ]
    saved_at = str(saved['timestamp'])
    generated_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    visible = [saved_at, generated_at, DISCLAIMER]
    visible.extend(_value(value) for _, rows in sections for _, value in rows)
    glyphs = pdfmetrics.getFont('TiboqSans').face.charToGlyph
    if any(ord(char) not in glyphs for body in visible for char in body if char not in '\n\r\t'):
        raise HTTPException(422, 'The bundled PDF font does not support some characters in this draft. Export was stopped to avoid losing text.')

    width, height = 595.28, 841.89
    content_width = width - 88
    selected = None
    for size in (9.5, 9, 8.5, 8):
        style = ParagraphStyle('field', fontName='TiboqSans', fontSize=size, leading=size * 1.38,
                               textColor=INK)
        layout = []
        total = 0
        for title, rows in sections:
            paragraphs = []
            for label, value in rows:
                markup = f'<b>{escape(label)}:</b> {escape(_value(value)).replace(chr(10), "<br/>")}'
                paragraph = Paragraph(markup, style)
                _, field_height = paragraph.wrap(content_width - 24, height)
                paragraphs.append((paragraph, field_height))
            block_height = 30 + sum(field_height + 5 for _, field_height in paragraphs) + 7
            layout.append((title, paragraphs, block_height))
            total += block_height + 8
        if total <= 628:
            selected = layout
            break
    if selected is None:
        raise HTTPException(422, 'This record is too long for a readable PDF. Export was stopped; no saved information was truncated.')

    output = BytesIO()
    page = canvas.Canvas(output, pagesize=(width, height))
    page.setTitle('TIBOQ encounter draft')
    page.setAuthor('TIBOQ local draft support')
    page.setFillColor(FOREST)
    page.rect(0, height - 12, width, 12, stroke=0, fill=1)
    page.setFont('TiboqSans-Bold', 23)
    page.drawString(44, 789, 'TIBOQ')
    page.setFillColor(MUTED)
    page.setFont('TiboqSans', 9)
    page.drawString(44, 772, 'SOAP PRACTICE DRAFT / FOR REVIEW AND STUDY ONLY')
    page.setStrokeColor(RULE)
    page.line(44, 759, width - 44, 759)
    page.setFont('TiboqSans', 8)
    page.drawString(44, 745, 'Saved: ' + saved_at)
    page.drawString(44, 732, 'Generated: ' + generated_at)
    y = 718
    for title, paragraphs, block_height in selected:
        page.setFillColor(MINT)
        page.roundRect(44, y - block_height, content_width, block_height, 6, stroke=0, fill=1)
        page.setFillColor(FOREST)
        page.setFont('TiboqSans-Bold', 9)
        page.drawString(56, y - 18, title)
        line_y = y - 25
        for paragraph, field_height in paragraphs:
            line_y -= field_height + 5
            paragraph.drawOn(page, 56, line_y)
        y -= block_height + 8
    page.setStrokeColor(RULE)
    page.line(44, 58, width - 44, 58)
    page.setFillColor(MUTED)
    page.setFont('TiboqSans', 7)
    page.drawString(44, 42, DISCLAIMER)
    page.showPage()
    page.save()
    return output.getvalue()
