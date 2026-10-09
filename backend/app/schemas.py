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

class CompletenessInput(StrictModel):
    record: Record


def empty_record() -> Record:
    return Record(patient=Patient(age=None, sex=None), chief_complaint=None, hpi=None,
                  past_history=None, medications=[], allergies=[],
                  vitals=Vitals(bp=None, hr=None, rr=None, temp_c=None, spo2=None),
                  physical_exam=None, assessment=None, plan=None)
