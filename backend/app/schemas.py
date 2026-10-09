from typing import Literal, Self
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False, str_max_length=30000)

class Patient(StrictModel):
    age: StrictInt | StrictFloat | None
    sex: str | None

class Vitals(StrictModel):
    bp: str | None
    hr: StrictInt | StrictFloat | None
    rr: StrictInt | StrictFloat | None
    temp_c: StrictInt | StrictFloat | None
    spo2: StrictInt | StrictFloat | None

class Record(StrictModel):
    patient: Patient
    chief_complaint: str | None
    hpi: str | None
    past_history: str | None
    medications: list[str]
    allergies: list[str]
    vitals: Vitals
    physical_exam: str | None
    assessment: str | None
    plan: str | None

class StructureInput(StrictModel):
    text: str = Field(min_length=1, max_length=30000)

class Warning(StrictModel):
    field: str
    message: str

class StructureResult(StrictModel):
    record: Record
    warnings: list[Warning]

class UnlockInput(StrictModel):
    password: str = Field(min_length=1, max_length=1024)

class DeidInput(StrictModel):
    text: str = Field(max_length=100000)

class SaveInput(StrictModel):
    record: Record
    confirmed: Literal[True]
    deid_keep: list[str] = Field(default_factory=list)
    warning_acknowledgements: list[str] = Field(default_factory=list)

class AskInput(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    scope: list[Literal['notes', 'guidelines', 'textbook']] = Field(default_factory=lambda: ['notes', 'guidelines', 'textbook'])

class TermLookupInput(StrictModel):
    term: str = Field(min_length=1, max_length=80)
    scope: list[Literal['notes', 'guidelines', 'textbook']] = Field(default_factory=lambda: ['notes', 'guidelines', 'textbook'])

class RAGCitation(StrictModel):
    chunk_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=1800)

class RAGResponse(StrictModel):
    status: Literal['answered', 'not_covered']
    answer: str = Field(min_length=1, max_length=4000)
    citations: list[RAGCitation] = Field(max_length=4)

    @model_validator(mode='after')
    def validate_status_payload(self) -> Self:
        if not self.answer.strip():
            raise ValueError('answer cannot be blank')
        if self.status == 'answered' and not self.citations:
            raise ValueError('answered responses require at least one citation')
        if self.status == 'not_covered' and self.citations:
            raise ValueError('not_covered responses cannot include citations')
        return self


class RAGModelResponse(StrictModel):
    """Small model output; the backend attaches exact citation excerpts."""
    model_config = ConfigDict(extra='ignore', strict=True, allow_inf_nan=False, str_max_length=30000)
    status: Literal['answered', 'not_covered']
    answer: str = Field(default='', max_length=4000)
    source_ids: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode='before')
    @classmethod
    def normalize_small_model_shape(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if 'answer' not in data and isinstance(data.get('response'), str):
            data['answer'] = data['response']
        answer = data.get('answer', '')
        status = str(data.get('status', '')).strip().lower().replace(' ', '_')
        if status in {'answer', 'covered', 'supported'}:
            data['status'] = 'answered'
        elif status in {'notcovered', 'unanswered', 'unsupported'}:
            data['status'] = 'not_covered'
        elif not status and isinstance(answer, str) and answer.strip():
            data['status'] = ('not_covered' if answer.strip().casefold() ==
                              'not covered by your library'.casefold() else 'answered')
        if 'source_ids' not in data:
            source = data.get('source_id') or data.get('chunk_id')
            if isinstance(source, str):
                data['source_ids'] = [source]
            else:
                citations = data.get('citations')
                if isinstance(citations, list):
                    data['source_ids'] = [item.get('source_id') or item.get('chunk_id')
                                          for item in citations if isinstance(item, dict)
                                          and isinstance(item.get('source_id') or item.get('chunk_id'), str)]
        if isinstance(data.get('source_ids'), str):
            data['source_ids'] = [data['source_ids']]
        if data.get('status') == 'not_covered':
            data['source_ids'] = []
        return data

    @model_validator(mode='after')
    def validate_status_payload(self) -> Self:
        if self.status == 'not_covered' and self.source_ids:
            raise ValueError('not_covered responses cannot include sources')
        return self

class CompletenessInput(StrictModel):
    record: Record


def empty_record() -> Record:
    return Record(patient=Patient(age=None, sex=None), chief_complaint=None, hpi=None,
                  past_history=None, medications=[], allergies=[],
                  vitals=Vitals(bp=None, hr=None, rr=None, temp_c=None, spo2=None),
                  physical_exam=None, assessment=None, plan=None)
