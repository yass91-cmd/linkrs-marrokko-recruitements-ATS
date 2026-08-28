from pydantic import BaseModel, Field, field_validator
from typing import Optional


class JobDetails(BaseModel):
    missions: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    contract_type: Optional[str] = None
    salary: Optional[str] = None
    schedule: Optional[str] = None
    benefits: list[str] = Field(default_factory=list)
    experience_required: Optional[str] = None

    @field_validator("missions", "requirements", "languages", "benefits", mode="before")
    @classmethod
    def none_to_list(cls, v):
        return [] if v is None else v