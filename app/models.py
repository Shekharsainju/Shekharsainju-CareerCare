import enum

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, ForeignKey,
    UniqueConstraint, Text, Enum as SAEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class Role(str, enum.Enum):
    user = "user"
    moderator = "moderator"
    admin = "admin"


class ListingStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApplicationStatus(str, enum.Enum):
    draft = "draft"          # AI has tailored it, user hasn't reviewed/sent yet
    ready = "ready"          # user has reviewed and is about to apply themselves
    applied = "applied"      # user has manually confirmed they submitted it
    interviewing = "interviewing"
    rejected = "rejected"
    withdrawn = "withdrawn"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(SAEnum(Role), nullable=False, default=Role.user)
    moderated_fields = Column(String, nullable=True, default="")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Account lockout — separate from the per-IP rate limit on the
    # login endpoint. IP-based limiting stops a single attacker
    # hammering the endpoint; this stops a distributed/rotating-IP
    # attacker credential-stuffing one specific account.
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    resumes = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="user", cascade="all, delete-orphan")

    def moderated_field_list(self) -> list[str]:
        return [f.strip() for f in (self.moderated_fields or "").split(",") if f.strip()]


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


class Internship(Base):
    __tablename__ = "internships"

    id = Column(Integer, primary_key=True, index=True)
    company = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    field = Column(String, nullable=False, index=True)
    city = Column(String, nullable=False, index=True)
    duration = Column(String, nullable=True)
    deadline = Column(String, nullable=True)
    salary = Column(String, nullable=True)  # free text (e.g. "$65k–$75k pro-rata"); None shown as "—" in the UI, most real internship listings don't state one
    # True/False require explicit acceptance/restriction evidence for imports;
    # None means unconfirmed. Sponsorship and work rights are separate signals.
    # Program-level evidence has its own source URL; user submissions are labelled.
    accepts_international = Column(Boolean, nullable=True)
    # Free text, curated — e.g. "Startup (~50)", "Small (~400)", "Mid
    # (~1,000)". Greenhouse/Lever's public APIs don't return employee
    # counts, so this can't be auto-detected from a scrape; it's set
    # per-company in scraper.py's COMPANY_BOARDS (for scraped
    # listings) or by whoever adds a listing (seed data, or a user
    # submission). None means genuinely unknown, not "large" by
    # default — never guessed from a company's fame or lack of it.
    company_size = Column(String, nullable=True)
    status = Column(SAEnum(ListingStatus), nullable=False, default=ListingStatus.approved, index=True)
    url = Column(String, nullable=False, unique=True)
    source = Column(String, nullable=True)
    description = Column(Text, nullable=True)  # optional free text — improves AI tailoring when present

    # Crowdsourced link-health: any listing can be reported broken by a
    # signed-in user. Once reports reach BROKEN_LINK_REPORT_THRESHOLD
    # (config.py), it's automatically hidden from the public board —
    # see routers/internships.py — without waiting for a human to
    # re-check it on a schedule. This exists because hand-verified
    # seed data goes stale the moment an employer closes a round after
    # the listing was added; see seed_data.py's docstring for the
    # incident that prompted this.
    broken_link_reports = Column(Integer, nullable=False, default=0)
    last_reported_broken_at = Column(DateTime(timezone=True), nullable=True)

    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Updated explicitly only when verified by a successful source fetch/review.
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    source_active = Column(Boolean, nullable=False, default=True, server_default="true")
    sponsorship_available = Column(Boolean, nullable=True)
    work_rights_note = Column(Text, nullable=True)
    eligibility_evidence = Column(Text, nullable=True)
    eligibility_source_url = Column(Text, nullable=True)
    opportunity_type = Column(String, default="job", nullable=True)


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "internship_id", name="uq_user_internship"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    internship_id = Column(Integer, ForeignKey("internships.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="favorites")


class Resume(Base):
    """A user's base resume — the ground truth the AI is allowed to
    draw from. Only one active resume per user for v1 (re-saving
    replaces it); kept as its own table so versioning is a small
    extension later rather than a schema change."""
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    raw_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="resumes")


class Application(Base):
    """A tailored-resume draft for one listing. Nothing here ever
    submits anything anywhere — status only changes when the user
    tells it to, including 'applied', which the user sets themselves
    after actually submitting the application on the employer's site."""
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "internship_id", name="uq_user_application"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    internship_id = Column(Integer, ForeignKey("internships.id"), nullable=False)

    tailored_resume = Column(Text, nullable=True)
    cover_letter = Column(Text, nullable=True)
    changes_summary = Column(Text, nullable=True)  # AI's plain-language note on what it changed and why
    learning_recommendations = Column(Text, nullable=True)  # AI's suggested skills/tools to learn, one per line
    project_idea = Column(Text, nullable=True)  # AI's suggested portfolio project for this specific role

    status = Column(SAEnum(ApplicationStatus), nullable=False, default=ApplicationStatus.draft)
    notes = Column(Text, nullable=True)  # user's own private notes

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    applied_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="applications")
    internship = relationship("Internship")


class DiscoverySource(Base):
    __tablename__ = "discovery_sources"
    source = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    checked_at = Column(DateTime(timezone=True))
    last_success_at = Column(DateTime(timezone=True))
    count = Column(Integer, default=0)
    message = Column(String)


class DiscoveryLease(Base):
    __tablename__ = "discovery_lease"
    id = Column(Integer, primary_key=True)
    lease_until = Column(DateTime(timezone=True), nullable=False)
    next_run_at = Column(DateTime(timezone=True), nullable=False)
