from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import Role, ListingStatus, ApplicationStatus

ALLOWED_FIELDS = {"Software", "Finance", "Consulting", "Data", "Marketing", "Research", "Government", "Engineering", "Design", "Operations"}


# ---------- Auth ----------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if v.isdigit() or v.isalpha():
            raise ValueError("Password must mix letters and numbers.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Only the access token goes in the response body. The refresh
    token is set as an httpOnly cookie instead — see routers/auth.py —
    so it's never readable by JavaScript on the page, unlike a token
    handed back in JSON and stashed in localStorage."""
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: Role
    moderated_fields: list[str] = []

    model_config = {"from_attributes": True}


# ---------- Internships ----------

class InternshipCreate(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=300)
    field: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=150)
    duration: Optional[str] = Field(default=None, max_length=150)
    deadline: Optional[str] = Field(default=None, max_length=100)
    salary: Optional[str] = Field(default=None, max_length=150)
    accepts_international: Optional[bool] = None
    company_size: Optional[str] = Field(default=None, max_length=100)
    url: str = Field(min_length=1, max_length=2000)

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("field")
    @classmethod
    def field_must_be_known(cls, v: str) -> str:
        if v not in ALLOWED_FIELDS:
            raise ValueError(f"field must be one of: {', '.join(sorted(ALLOWED_FIELDS))}")
        return v


class InternshipOut(BaseModel):
    id: int
    company: str
    role: str
    field: str
    city: str
    duration: Optional[str]
    deadline: Optional[str]
    salary: Optional[str]
    accepts_international: Optional[bool]
    company_size: Optional[str]
    status: ListingStatus
    url: str
    source: Optional[str]
    submitted_by_id: Optional[int]
    scraped_at: Optional[datetime]
    first_seen_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    source_active: bool = True
    source_connection_issue: bool = False
    verification_overdue: bool = False
    sponsorship_available: Optional[bool] = None
    work_rights_note: Optional[str] = None
    eligibility_evidence: Optional[str] = None
    eligibility_source_url: Optional[str] = None
    opportunity_type: Optional[str] = "job"
    is_favorited: bool = False
    broken_link_reports: int = 0

    model_config = {"from_attributes": True}


class ModerationDecision(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


# ---------- Admin ----------

class PromoteRequest(BaseModel):
    role: Role
    moderated_fields: list[str] = []

    @field_validator("moderated_fields")
    @classmethod
    def fields_must_be_known(cls, v: list[str]) -> list[str]:
        unknown = set(v) - ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"Unknown field(s): {', '.join(sorted(unknown))}")
        return v


# ---------- Resume ----------

class ResumeIn(BaseModel):
    raw_text: str = Field(min_length=50, max_length=20000)


class ResumeOut(BaseModel):
    id: int
    raw_text: str
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------- Applications ----------

class ApplicationOut(BaseModel):
    id: int
    internship_id: int
    tailored_resume: Optional[str]
    cover_letter: Optional[str]
    changes_summary: Optional[str]
    learning_recommendations: list[str] = []
    project_idea: Optional[str]
    status: ApplicationStatus
    notes: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    applied_at: Optional[datetime]

    # Denormalized at read time from the linked Internship row, so the
    # tracker table can render company/role/salary without a second
    # client-side fetch-and-match — which would silently miss a
    # pending or rejected listing the user applied to before it (or
    # instead of it) getting approved.
    company: str
    role: str
    url: str
    salary: Optional[str]

    model_config = {"from_attributes": True}


class ApplicationUpdate(BaseModel):
    tailored_resume: Optional[str] = Field(default=None, max_length=20000)
    cover_letter: Optional[str] = Field(default=None, max_length=8000)
    notes: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[ApplicationStatus] = None
