"""Heuristic warnings only. This is not an anonymization guarantee."""
import hashlib
import re
from app.schemas import Record

PATTERNS = {
    'Email address': r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',
    'Phone number': r'(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{3,4}[ .-]\d{3,4}(?!\w)',
    'Possible hospital / ID number': r'(?<!\d)\d{7,}(?!\d)',
    'Full date / possible birthdate': r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4})\b',
}
NAME = re.compile(r'\b(?i:Mr\.|Mrs\.|Ms\.|Patient name\s*:?|Pt\.)\s+([A-ZÀ-ÖØ-Þ][a-zA-ZÀ-ÖØ-öø-ÿ\'’-]+(?:[ ][A-ZÀ-ÖØ-Þ][a-zA-ZÀ-ÖØ-öø-ÿ\'’-]+){0,3})')


def scan(text: str, field: str = '') -> list[dict]:
    hits = []
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text, re.I):
            hits.append((match.start(), match.end(), kind))
    for match in NAME.finditer(text):
        hits.append((match.start(1), match.end(1), 'Possible patient name'))
    result = []
    for start, end, kind in sorted(set(hits)):
        token = hashlib.sha256(f'{field}|{start}|{end}|{kind}|{text[start:end]}'.encode()).hexdigest()[:24]
        result.append({'id': token, 'kind': kind, 'text': text[start:end], 'start': start, 'end': end, 'field': field})
    return result


def scan_record(record: Record) -> list[dict]:
    result = []
    for key, value in record.model_dump().items():
        if isinstance(value, dict):
            for child, text in value.items():
                if isinstance(text, str):
                    result.extend(scan(text, f'{key}.{child}'))
        elif isinstance(value, list):
            result.extend(scan('\n'.join(value), key))
        elif isinstance(value, str):
            result.extend(scan(value, key))
    return result
