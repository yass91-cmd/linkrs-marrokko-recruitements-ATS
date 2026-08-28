from pydantic import BaseModel, Field, field_validator
from typing import Optional


class Education(BaseModel):
    degree: Optional[str] = None
    institution: Optional[str] = None
    year: Optional[str] = None


class Experience(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    duration: Optional[str] = None


class Candidate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    years_experience: Optional[float] = None
    summary: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "skills", "languages", "education", "experience", "projects", "warnings",
        mode="before",
    )
    @classmethod
    def none_to_list(cls, v):
        # LLMs sometimes return null instead of [] — coerce it defensively.
        return [] if v is None else v