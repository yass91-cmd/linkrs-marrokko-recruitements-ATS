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


class PastedJob(BaseModel):
    """A whole advert pasted from a job board: identity plus the structured body.

    The collector never uses this — there, title/employer/city come from the API
    and are authoritative. Here they have to be read out of the text itself.
    """
    title: Optional[str] = None
    employer: Optional[str] = None
    city: Optional[str] = None
    is_remote: bool = False
    details: JobDetails = Field(default_factory=JobDetails)

    @field_validator("is_remote", mode="before")
    @classmethod
    def none_to_false(cls, v):
        return False if v is None else v