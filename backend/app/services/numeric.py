"""Review aids; these ranges are plausibility checks, never clinical interpretation."""
import re
from app.schemas import Record, Vitals, Warning

RANGES = {'hr': (20, 250), 'rr': (4, 60), 'temp_c': (30, 43), 'spo2': (50, 100)}


def validate_vitals(vitals: Vitals) -> list[Warning]:
    warnings = []
    for key, (low, high) in RANGES.items():
        value = getattr(vitals, key)
        if value is not None and not low <= value <= high:
            warnings.append(Warning(field=f'vitals.{key}', message=f'{value} is outside the plausibility range {low}–{high}. Confirm the value and unit.'))
    if vitals.bp is not None:
        match = re.fullmatch(r'\s*(\d{1,4})\s*/\s*(\d{1,4})(?:\s*mmHg)?\s*', vitals.bp, re.I)
        if not match:
            warnings.append(Warning(field='vitals.bp', message='Use systolic/diastolic, e.g. 120/80. Confirm the source.'))
        else:
            systolic, diastolic = map(int, match.groups())
            if not (50 <= systolic <= 300 and 20 <= diastolic <= 200) or systolic <= diastolic:
                warnings.append(Warning(field='vitals.bp', message='Blood pressure is outside the plausibility range or systolic is not above diastolic. Confirm both values.'))
    return warnings


def validate_record(record: Record) -> list[Warning]:
    warnings = validate_vitals(record.vitals)
    age = record.patient.age
    if age is not None and not 0 <= age <= 120:
        warnings.append(Warning(field='patient.age', message='Age is outside 0–120 years. Confirm the value and unit.'))
    texts = {field: getattr(record, field) or '' for field in ('chief_complaint', 'hpi', 'physical_exam', 'assessment', 'plan', 'past_history')}
    texts['medications'] = '\n'.join(record.medications)
    texts['allergies'] = '\n'.join(record.allergies)
    dose_pattern = r'(?<![\w.,])[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?\s*(?:mcg|mg|g|mL|ml|units?|IU|tablets?)\b'
    vital_patterns = {
        'hr': r'\b(?:HR|heart rate|pulse)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
        'rr': r'\b(?:RR|respiratory rate)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
        'temp_c': r'\b(?:temp(?:erature)?(?:_c)?)\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*°?\s*(?:C\b|Celsius\b)',
        'spo2': r'\b(?:SpO2|oxygen saturation|o2 sat)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
    }
    for field, value in texts.items():
        doses = re.findall(dose_pattern, value, re.I)
        for dose in doses:
            warnings.append(Warning(field=field, message=f'Confirm dose {dose} against the source; this tool does not validate prescribing doses.'))
        if field == 'medications' and re.search(r'\d', value) and not doses:
            warnings.append(Warning(field=field, message='Medication text contains numbers without a recognized dose unit. Confirm amount, frequency, and units.'))
        for lab in re.findall(r'\b(?:Hb|hemoglobin|WBC|platelets|Na|sodium|K|potassium|creatinine|glucose|CRP|lactate)\s*[:=]?\s*-?\d+(?:\.\d+)?\s*[a-zA-Z/%]*', value, re.I):
            warnings.append(Warning(field=field, message=f'Confirm lab value and units: {lab}. No clinical interpretation is applied.'))
        # Vitals embedded in free-text fields must not bypass deterministic checks.
        for vital, pattern in vital_patterns.items():
            low, high = RANGES[vital]
            for found in re.findall(pattern, value, re.I):
                if not low <= float(found) <= high:
                    warnings.append(Warning(field=field, message=f'{vital} {found} in this text is outside {low}–{high}. Confirm the value and unit.'))
        for bp in re.findall(r'\b(?:BP|blood pressure)\s*[:=]?\s*(-?\d+\s*/\s*-?\d+)', value, re.I):
            for warning in validate_vitals(Vitals(bp=bp, hr=None, rr=None, temp_c=None, spo2=None)):
                warnings.append(Warning(field=field, message='BP in this text: ' + warning.message))
    return warnings
