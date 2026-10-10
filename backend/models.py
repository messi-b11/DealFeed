from datetime import date
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

class ProposalInput(StrictModel):
    price: float = Field(ge=0.01, le=1000000, allow_inf_nan=False)
    currency: str = Field(default="USD", pattern="^USD$")
    scope: str = Field(min_length=20, max_length=5000)
    timeline: str = Field(min_length=3, max_length=500)

class ProjectInput(StrictModel):
    title: str = Field(min_length=5, max_length=180)
    client: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=20, max_length=3000)
    category: str = Field(pattern="^(Restaurant|E-commerce|Wellness|Professional services)$")
    result: str = Field(min_length=5, max_length=200)
    image: str = Field(default="/projects/olive.svg", max_length=3000000)
