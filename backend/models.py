from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class BuyerInput(StrictModel):
    projectId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    budget: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=2, max_length=160)
    deadline: date
    requirements: str = Field(min_length=20, max_length=5000)

    @field_validator("deadline")
    @classmethod
    def future_deadline(cls, value):
        if value < date.today():
            raise ValueError("Choose today or a future deadline.")
        return value

class Brief(StrictModel):
    title: str = Field(min_length=3, max_length=180)
    summary: str = Field(min_length=20, max_length=5000)
    deliverables: list[str] = Field(min_length=1, max_length=20)
    questions: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    reference: str = Field(min_length=1, max_length=500)

    @field_validator("deliverables", "questions", "constraints")
    @classmethod
    def nonempty_items(cls, values):
        if any(not value.strip() or len(value) > 1000 for value in values):
            raise ValueError("List entries must contain 1–1000 characters.")
        return [value.strip() for value in values]

class Approval(StrictModel):
    draftId: str = Field(min_length=1, max_length=100)
    approved: bool
    brief: Brief

class DeliverableCoverage(StrictModel):
    deliverableId: str = Field(min_length=1, max_length=100)
    status: Literal["included", "excluded", "partial", "not_stated"]
    detail: str = Field(default="", max_length=2000)

class ProposalInput(StrictModel):
    price: float = Field(ge=0.01, le=1000000, allow_inf_nan=False)
    currency: str = Field(default="USD", pattern="^USD$")
    scope: str = Field(min_length=20, max_length=5000)
    timeline: str = Field(min_length=3, max_length=500)
    fitStatement: str = Field(default="", max_length=5000)
    approach: str = Field(default="", max_length=5000)
    coverage: list[DeliverableCoverage] = Field(default_factory=list, max_length=30)
    exclusions: list[str] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    clarifications: list[str] = Field(default_factory=list, max_length=30)
    comparableProjectIds: list[str] = Field(default_factory=list, max_length=10)
    achievementIds: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("exclusions", "assumptions", "clarifications", "comparableProjectIds", "achievementIds")
    @classmethod
    def valid_entries(cls, values):
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("Entries must contain 1–2000 characters.")
        if len(values) != len(set(values)):
            raise ValueError("Duplicate entries are not allowed.")
        return [value.strip() for value in values]

    @field_validator("coverage")
    @classmethod
    def unique_coverage(cls, values):
        if len(values) != len({value.deliverableId for value in values}):
            raise ValueError("Each deliverable can appear only once.")
        return values

class Deliverable(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=2, max_length=1000)
    mandatory: bool = True

class MatchCriteria(StrictModel):
    inspirationProjectIds: list[str] = Field(min_length=1, max_length=10)
    description: str = Field(min_length=20, max_length=5000)
    serviceCategory: str = Field(pattern="^(Catering|Event decorations|Website development|Keynote speaking|Restaurant|E-commerce|Wellness|Professional services)$")
    budgetCents: int | None = Field(default=None, ge=1, le=100000000, strict=True)
    currency: Literal["USD"] = "USD"
    deliverables: list[Deliverable] = Field(min_length=1, max_length=30)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    mustHaves: list[str] = Field(default_factory=list, max_length=30)
    desiredStandard: str = Field(default="", max_length=2000)
    location: str = Field(default="", max_length=160)
    deliveryMode: Literal["remote", "onsite", "hybrid"] = "remote"
    targetDate: date | None = None
    buyerName: str = Field(default="", max_length=120)
    preferencesConfirmed: bool = False

    @field_validator("inspirationProjectIds", "keywords", "mustHaves")
    @classmethod
    def valid_criteria_entries(cls, values):
        values = [value.strip() for value in values]
        if any(not value or len(value) > 1000 for value in values):
            raise ValueError("Entries must contain 1–1000 characters.")
        if len(values) != len(set(values)):
            raise ValueError("Duplicate entries are not allowed.")
        return values

    @field_validator("deliverables")
    @classmethod
    def unique_deliverables(cls, values):
        if len(values) != len({value.id for value in values}):
            raise ValueError("Deliverables must have distinct stable IDs.")
        return values

    @field_validator("targetDate")
    @classmethod
    def valid_target_date(cls, value):
        if value and value < date.today():
            raise ValueError("Choose today or a future target date.")
        return value

class MatchInput(StrictModel):
    criteria: MatchCriteria

class DealApproval(StrictModel):
    matchRunId: str = Field(min_length=1, max_length=100)
    businessIds: list[str] = Field(min_length=1, max_length=5)
    approved: bool
    idempotencyKey: str = Field(min_length=8, max_length=160)

    @field_validator("businessIds")
    @classmethod
    def unique_recipients(cls, values):
        if len(values) != len(set(values)) or any(not value.strip() for value in values):
            raise ValueError("Choose one to five distinct businesses.")
        return values

class SelectionInput(StrictModel):
    requestId: str = Field(min_length=1, max_length=100)

class ProjectInput(StrictModel):
    title: str = Field(min_length=5, max_length=180)
    client: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=20, max_length=3000)
    category: str = Field(pattern="^(Catering|Event decorations|Website development|Keynote speaking|Restaurant|E-commerce|Wellness|Professional services)$")
    result: str = Field(min_length=5, max_length=200)
    image: str = Field(default="/projects/photos/olive-website.jpg", max_length=3000000)
