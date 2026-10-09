import asyncio
import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from app.schemas import empty_record, Record
from app.services.numeric import validate_vitals, validate_record
from app.services.structure import grounded
from app.services import llm


def test_vitals_ranges_and_bp():
    record = empty_record()
    record.vitals.hr = 251
    record.vitals.rr = 3
    record.vitals.temp_c = 44
    record.vitals.spo2 = 101
    record.vitals.bp = '40/210'
    assert {w.field for w in validate_vitals(record.vitals)} == {'vitals.hr', 'vitals.rr', 'vitals.temp_c', 'vitals.spo2', 'vitals.bp'}
    record.vitals.hr = 20
    record.vitals.rr = 60
    record.vitals.temp_c = 30
    record.vitals.spo2 = 50
    record.vitals.bp = '120/80'
    assert not validate_vitals(record.vitals)
    record.vitals.bp = 'elevated'
    assert validate_vitals(record.vitals)


def test_schema_strict():
    data = empty_record().model_dump()
    data['vitals']['hr'] = '90'
    with pytest.raises(ValidationError):
        Record.model_validate(data)
    data['vitals']['hr'] = 90
    data['invented'] = 'value'
    with pytest.raises(ValidationError):
        Record.model_validate(data)
    del data['invented']
    del data['allergies']
    with pytest.raises(ValidationError):
        Record.model_validate(data)


def test_unstated_numbers_and_diagnosis_removed():
    record = empty_record()
    record.patient.age = 28
    record.vitals.hr = 28
    record.vitals.temp_c = 37
    record.assessment = 'pneumonia'
    record.plan = 'Start antibiotics'
    result = grounded(record, '28-year-old. Temp 37 F. Rule out pneumonia.')
    assert result.record.patient.age == 28
    assert result.record.vitals.hr is None
    assert result.record.vitals.temp_c is None
    assert result.record.assessment is None
    assert result.record.plan is None


def test_verbatim_assessment_retains_uncertainty():
    record = empty_record()
    record.assessment = 'pneumonia'
    assert grounded(record, 'Assessment: rule out pneumonia').record.assessment is None
    record.assessment = 'rule out pneumonia'
    assert grounded(record, 'Assessment: rule out pneumonia').record.assessment == 'rule out pneumonia'


def test_doses_and_labs_require_confirmation():
    record = empty_record()
    record.medications = ['amoxicillin 500 mg']
    record.hpi = 'glucose 400 mg/dL'
    assert {w.field for w in validate_record(record)} == {'medications', 'hpi'}


def test_json_retry_once(monkeypatch):
    calls = []
    async def fake(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError('invalid JSON')
        return empty_record().model_dump()
    monkeypatch.setattr(llm, 'generate_json', fake)
    assert asyncio.run(llm.extract('encounter')) == empty_record()
    assert len(calls) == 2


def test_invalid_twice_clean_failure(monkeypatch):
    calls = []
    async def fake(*args, **kwargs):
        calls.append(1)
        return {'bad': 'schema'}
    monkeypatch.setattr(llm, 'generate_json', fake)
    with pytest.raises(HTTPException) as error:
        asyncio.run(llm.extract('encounter'))
    assert error.value.status_code == 502
    assert len(calls) == 2


def test_stripped_negation_and_uncertainty_are_removed():
    record = empty_record(); record.hpi = 'fever'; record.chief_complaint = 'chest pain'
    record.allergies = ['penicillin']; record.medications = ['aspirin']
    result = grounded(record, 'Denies fever. No chest pain. Allergies: not allergic to penicillin. Medications: not taking aspirin.')
    assert result.record.hpi is None and result.record.chief_complaint is None
    assert result.record.allergies == [] and result.record.medications == []
    record.hpi = 'Denies fever'; record.medications = ['not taking aspirin']
    result = grounded(record, 'Denies fever. Medications: not taking aspirin.')
    assert result.record.hpi == 'Denies fever'
    assert result.record.medications == ['not taking aspirin']


def test_medication_cannot_be_inferred_from_allergy():
    record = empty_record(); record.medications = ['penicillin']
    assert grounded(record, 'Allergies: penicillin. Medications: aspirin.').record.medications == []


def test_numbers_in_free_text_do_not_bypass_checks():
    record = empty_record(); record.hpi = 'HR 300, BP 40/20, took aspirin -500 mg, glucose 400.'
    warnings = validate_record(record)
    assert any('hr 300' in w.message for w in warnings)
    assert any('BP in this text' in w.message for w in warnings)
    assert any('dose -500 mg' in w.message for w in warnings)
    assert any('lab value' in w.message for w in warnings)
    record.medications = ['aspirin 500']
    assert any('without a recognized dose unit' in w.message for w in validate_record(record))


def test_explicit_numbers_recovered_and_ambiguous_or_family_values_empty():
    record = empty_record()
    result = grounded(record, '28-year-old female. BP 118/76. HR 88. RR 18. Temperature 36.8 C. SpO2 98%.')
    assert result.record.patient.age == 28 and result.record.vitals.hr == 88
    assert result.record.vitals.bp == '118/76'
    assert grounded(record, 'Age is 18, sex is male.').record.patient.age == 18
    result = grounded(record, 'HR 88 then HR 90. Mother is 45-year-old, BP 120/80.')
    assert result.record.vitals.hr is None and result.record.vitals.bp is None and result.record.patient.age is None
    assert grounded(record, 'BP 16/10 kPa.').record.vitals.bp is None


def test_subword_excerpts_cannot_reverse_exam_findings():
    record = empty_record(); record.physical_exam = 'tender'; record.hpi = 'febrile'
    result = grounded(record, 'Physical exam: nontender. The patient is afebrile.')
    assert result.record.physical_exam is None and result.record.hpi is None


def test_numeric_tokens_cannot_be_silently_truncated():
    record = empty_record()
    result = grounded(record, 'HR 1,000. RR 2e2. BP 120/80.5.')
    assert result.record.vitals.hr is None and result.record.vitals.rr is None and result.record.vitals.bp is None
    record.medications = ['Drug 1,000 mg']
    assert any('1,000 mg' in w.message for w in validate_record(record))
