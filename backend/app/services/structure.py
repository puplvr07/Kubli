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
        # Include a final punctuation mark inside the quote, without reading
        # qualifiers from the next (possibly unrelated) sentence.
        right_candidates = [x for x in (source.find('.', match.end() - 1), source.find(';', match.end() - 1)) if x >= 0]
        right = min(right_candidates) if right_candidates else len(source)
        context = source[max(left, match.start()-100):min(right, match.end()+50)]
        if all(term.group(0) in quote for term in qualifiers.finditer(context)):
            return True
    return False


def stated_numbers(text: str, field: str) -> list[float]:
    labels = {
        'age': r'(?:\bage\s*(?:(?:is|[:=])\s*)?(-?\d+(?:\.\d+)?)|(?<!\d)(-?\d+(?:\.\d+)?)\s*(?:years?\s*old|[ -]?year[ -]old|yo\b|y/o\b))',
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
        value = next(group for group in match.groups() if group is not None)
        values.append(float(value))
    return sorted(set(values))


def numeric_evidence(text: str, field: str, value: float) -> bool:
    return value in stated_numbers(text, field)


def stated_patient_sex(text: str) -> str | None:
    """Accept only explicit patient descriptors, never relatives or pronouns."""
    values = set()
    patterns = (
        r'\b\d+\s*(?:-\s*year\s*-\s*old|years?\s+old)\s+(female|male)\b',
        r'\b(?:patient|sex)\s*(?:is|:|=)\s*(female|male)\b',
        r'\b(female|male)\s+patient\b',
    )
    for clause in re.split(r'[.;\n]', text):
        if re.search(r'\b(?:family history|mother|father|sister|brother|daughter|son|wife|husband)\b', clause, re.I):
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, clause, re.I):
                prefix = clause[max(0, match.start() - 40):match.start()]
                suffix = clause[match.end():]
                if re.search(r'\b(?:possible|possibly|suspected|uncertain|unknown|maybe|perhaps)\b', prefix, re.I):
                    continue
                if re.search(r'\b(?:not|no)\s*$', prefix, re.I):
                    continue
                if re.match(r'\s*(?:\?|/|or\s+(?:male|female)\b|\(uncertain\))', suffix, re.I):
                    continue
                values.add(match.group(1).lower())
    return next(iter(values)) if len(values) == 1 else None


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


SECTION_LABEL = re.compile(
    r'\b(?P<label>history of present illness|hpi|physical examination|physical exam|'
    r'assessment|impression|diagnosis|plan|past history|medical history|'
    r'medications?|meds|allergies|allergy|chief complaint|vitals)\s*:\s*', re.I)
VITAL_START = re.compile(
    r'\b(?:blood pressure|bp|heart rate|hr|respiratory rate|rr|temperature|temp|spo2)\s*[:=]?\s*\d', re.I)


def explicit_spans(text: str) -> dict[str, str]:
    """Return unique, bounded source spans for supported SOAP fields."""
    labels = list(SECTION_LABEL.finditer(text))
    found: dict[str, list[str]] = {'hpi': [], 'physical_exam': [], 'assessment': [], 'plan': []}
    aliases = {
        'history of present illness': 'hpi', 'hpi': 'hpi',
        'physical examination': 'physical_exam', 'physical exam': 'physical_exam',
        'assessment': 'assessment', 'impression': 'assessment', 'diagnosis': 'assessment',
        'plan': 'plan',
    }
    for index, label in enumerate(labels):
        field = aliases.get(label.group('label').lower())
        if field is None:
            continue
        end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        vital = VITAL_START.search(text, label.end(), end)
        if vital:
            end = vital.start()
        value = text[label.end():end].strip(' \t\r\n;.')
        if value:
            found[field].append(value)
    if not found['hpi']:
        end = labels[0].start() if labels else len(text)
        vital = VITAL_START.search(text, 0, end)
        if vital:
            end = vital.start()
        opening = text[:end].strip(' \t\r\n;.')
        if re.search(r'\b(?:reports?|complains? of|presents? with)\b', opening, re.I):
            found['hpi'].append(opening)
    result = {}
    for field, values in found.items():
        unique = {normalized(value) for value in values}
        if len(unique) != 1:
            continue
        value = values[0]
        if normalized(value) in {'not stated', 'none', 'unknown', 'n/a'}:
            continue
        if re.search(r'\b(?:denies?|denied|no|without|negative for|possible|possibly|suspected|uncertain|maybe|perhaps)\b', value, re.I):
            continue
        result[field] = value
    return result


def grounded(record: Record, text: str) -> StructureResult:
    """Fail closed: unsupported output is dropped, never repaired with invented data."""
    warnings: list[Warning] = []
    data = record.model_dump()
    source = normalized(text)
    spans = explicit_spans(text)
    def drop(field: str):
        warnings.append(Warning(field=field, message='Unsupported or ambiguous AI output was rejected. Numeric fields use only unambiguous source values; review this field.'))
    for field in ('chief_complaint', 'hpi', 'past_history', 'physical_exam', 'assessment', 'plan'):
        value = data[field]
        if value is None:
            continue
        supported = quote_supported(value, text)
        if field in ('hpi', 'physical_exam', 'assessment', 'plan'):
            bounded = spans.get(field)
            if bounded is not None:
                supported = supported and normalized(value).rstrip('.') in normalized(bounded).rstrip('.')
            elif field in ('assessment', 'plan'):
                supported = False
            elif SECTION_LABEL.search(text):
                if field == 'hpi':
                    first_label = SECTION_LABEL.search(text)
                    supported = supported and normalized(value) in normalized(text[:first_label.start()])
                else:
                    supported = False
        if not supported:
            data[field] = None
            drop(field)
    for field in ('hpi', 'physical_exam', 'assessment'):
        original = getattr(record, field)
        if data[field] is None and field in spans and (original is None or quote_supported(original, text)):
            data[field] = spans[field]
    sex = data['patient']['sex']
    explicit_sex = stated_patient_sex(text)
    if sex is not None and (explicit_sex is None or sex.strip().casefold() != explicit_sex):
        drop('patient.sex')
    data['patient']['sex'] = explicit_sex
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
