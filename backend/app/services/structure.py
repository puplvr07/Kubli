import re
from app.schemas import Record, StructureResult, Warning
from app.services import llm
from app.services.numeric import validate_record


def normalized(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip().casefold()


def quote_supported(value: str, text: str) -> bool:
    """Reject excerpts that strip negation, uncertainty, or family-history context."""
    source = normalized(text)
    quote = normalized(value)
    if not quote:
        return False
    qualifiers = re.compile(r'\b(?:no|not|denies?|denied|without|negative for|rule out|possible|suspected|family history|mother|father)\b')
    for match in re.finditer(r'(?<!\w)' + re.escape(quote) + r'(?!\w)', source):
        left = max(source.rfind('.', 0, match.start()), source.rfind(';', 0, match.start())) + 1
        right_candidates = [x for x in (source.find('.', match.end()), source.find(';', match.end())) if x >= 0]
        right = min(right_candidates) if right_candidates else len(source)
        context = source[max(left, match.start()-100):min(right, match.end()+50)]
        if all(term.group(0) in quote for term in qualifiers.finditer(context)):
            return True
    return False


def stated_numbers(text: str, field: str) -> list[float]:
    labels = {
        'age': r'(?:age\s*[:=]?\s*|(?<!\d))(-?\d+(?:\.\d+)?)\s*(?:years?\s*old|[ -]?year[ -]old|yo\b|y/o\b)',
        'hr': r'\b(?:hr|heart rate|pulse)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
        'rr': r'\b(?:rr|respiratory rate|respirations)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
        'temp_c': r'\b(?:temp(?:erature)?(?:_c)?)\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*°?\s*(?:C\b|Celsius\b)',
        'spo2': r'\b(?:spo2|oxygen saturation|o2 sat(?:uration)?)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
    }
    values = []
    for match in re.finditer(labels[field], text, re.I):
        left = max(text.rfind('.', 0, match.start()), text.rfind(';', 0, match.start()), text.rfind('\n', 0, match.start())) + 1
        prefix = text[left:match.start()].lower()
        if re.search(r'\b(?:mother|father|family history|denies|not|no)\b', prefix):
            continue
        if re.match(r'(?:\d|\.\d|,\d|[eE][-+]?\d)', text[match.end():]):
            continue
        values.append(float(match.group(1)))
    return sorted(set(values))


def numeric_evidence(text: str, field: str, value: float) -> bool:
    return value in stated_numbers(text, field)


def stated_pressures(text: str) -> list[str]:
    pressures = []
    for match in re.finditer(r'\b(?:bp|blood pressure)\s*[:=]?\s*(-?\d+\s*/\s*-?\d+)', text, re.I):
        left = max(text.rfind('.', 0, match.start()), text.rfind(';', 0, match.start()), text.rfind('\n', 0, match.start())) + 1
        prefix = text[left:match.start()].lower()
        suffix = text[match.end():match.end()+8].lower()
        if re.search(r'\b(?:mother|father|family history|denies|not|no)\b', prefix) or re.match(r'\s*kpa\b', suffix):
            continue
        if re.match(r'(?:\d|\.\d|,\d|[eE][-+]?\d)', text[match.end():]):
            continue
        pressures.append(match.group(1))
    return sorted(set(pressures))


def grounded(record: Record, text: str) -> StructureResult:
    """Fail closed: unsupported output is dropped, never repaired with invented data."""
    warnings: list[Warning] = []
    data = record.model_dump()
    source = normalized(text)
    def drop(field: str):
        warnings.append(Warning(field=field, message='Unsupported or ambiguous AI output was rejected. Numeric fields use only unambiguous source values; review this field.'))
    for field in ('chief_complaint', 'hpi', 'past_history', 'physical_exam', 'assessment', 'plan'):
        value = data[field]
        if value is None:
            continue
        supported = quote_supported(value, text)
        if field in ('assessment', 'plan'):
            label = r'(?:assessment|impression|diagnosis)' if field == 'assessment' else r'plan'
            sections = re.findall(r'\b' + label + r'\s*:\s*([^\n;]+)', text, re.I)
            supported = supported and any(normalized(value).rstrip('.') == normalized(s).rstrip('.') for s in sections)
        if not supported:
            data[field] = None
            drop(field)
    sex = data['patient']['sex']
    if sex is not None and (not quote_supported(sex, text) or not re.search(r'(?<!\w)' + re.escape(sex) + r'(?!\w)', text, re.I)):
        data['patient']['sex'] = None
        drop('patient.sex')
    for field in ('medications', 'allergies'):
        label = r'(?:allergies|allergy|allergic to)' if field == 'allergies' else r'(?:medications?|meds|takes?|taking|given|prescribed)'
        clauses = re.split(r'[\n;]|(?<!\d)\.(?!\d)', text)
        accepted = [x for x in data[field] if any(re.search(r'\b' + label + r'\b', clause, re.I) and quote_supported(x, clause) for clause in clauses)]
        if accepted != data[field]:
            drop(field)
        data[field] = accepted
    # Numeric extraction is deterministic: use only a unique explicitly stated value.
    # This also recovers clear numeric evidence the model left null, without guessing.
    for field, container in [('age', data['patient'])] + [(field, data['vitals']) for field in ('hr', 'rr', 'temp_c', 'spo2')]:
        values = stated_numbers(text, field)
        old = container[field]
        explicit = values[0] if len(values) == 1 else None
        if old is not None and (explicit is None or old != explicit):
            drop('patient.age' if field == 'age' else 'vitals.' + field)
        container[field] = int(explicit) if explicit is not None and explicit.is_integer() else explicit
    pressures = stated_pressures(text)
    source_bp = pressures[0] if len(pressures) == 1 else None
    old_bp = data['vitals']['bp']
    if old_bp is not None and (source_bp is None or normalized(old_bp).replace(' ', '').removesuffix('mmhg') != normalized(source_bp).replace(' ', '')):
        drop('vitals.bp')
    data['vitals']['bp'] = source_bp
    clean = Record.model_validate(data)
    return StructureResult(record=clean, warnings=warnings + validate_record(clean))


async def structure(text: str) -> StructureResult:
    return grounded(await llm.extract(text), text)
