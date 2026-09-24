from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_current_user_optional, require_field_moderator, require_role
from ..models import Internship, ListingStatus, Favorite, User, Role, DiscoverySource, DiscoveryLease
from ..rate_limiter import limiter
from ..schemas import InternshipCreate, InternshipOut, ModerationDecision
from ..security_log import log_permission_denied

router = APIRouter(prefix="/api/internships", tags=["internships"])


def _to_out(row: Internship, favorited_ids: set[int], source=None) -> InternshipOut:
    out = InternshipOut.model_validate(row)
    out.is_favorited = row.id in favorited_ids
    if (source and source.status in ("error", "partial") and source.last_success_at
            and row.scraped_at and source.checked_at
            and source.checked_at.replace(tzinfo=timezone.utc) > row.scraped_at.replace(tzinfo=timezone.utc)
            and row.source_active and row.source != "seed" and not (row.source or "").startswith("user:")):
        out.source_connection_issue = True
        out.verification_overdue = row.scraped_at.replace(tzinfo=timezone.utc) < _freshness_cutoff()
    return out


def _freshness_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=settings.freshness_window_days)


def _visible_freshness():
    # An outage is not evidence that a previously verified job has closed.
    failed_source = DiscoverySource.__table__.select().with_only_columns(DiscoverySource.source).where(
        DiscoverySource.source == Internship.source,
        DiscoverySource.status.in_(("error", "partial")),
        DiscoverySource.last_success_at.is_not(None),
        DiscoverySource.checked_at > Internship.scraped_at,
        Internship.source != "seed",
        ~Internship.source.like("user:%"),
    ).exists()
    return or_(Internship.scraped_at >= _freshness_cutoff(), failed_source)


# Ranks a listing's free-text company_size for the "least competition
# first" sort — lower rank = smaller company = sorted earlier. This
# is a heuristic over curated text (see scraper.py's COMPANY_BOARDS
# comment for where these strings actually come from), not a
# guarantee of actual applicant volume; a company's real competition
# level isn't something this app can measure directly, but company
# size is the closest honest proxy it has.
_SIZE_TIER_RANK = {"startup": 0, "small": 1, "mid": 2, "medium": 2, "large": 3}


def _size_rank(company_size: Optional[str]) -> float:
    if not company_size:
        return 2.5  # unknown — sorted after small/mid, before/around large, rather than assumed small or large
    lowered = company_size.lower()
    for keyword, rank in _SIZE_TIER_RANK.items():
        if keyword in lowered:
            return rank
    return 2.5


@router.get("", response_model=list[InternshipOut])
@limiter.limit("120/minute")
def list_internships(
    request: Request, field: Optional[str] = None, city: Optional[str] = None, search: Optional[str] = None,
    sort: str = "international", international_only: bool = False,
    db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user_optional),
):
    """Active approved jobs, including warned outage-retained results.

    International-first sorting is the default. Newest sorts by employer publish
    date when supplied, otherwise first discovery. An eligibility flag is not
    a guarantee that an individual candidate meets every requirement.
    """
    q = db.query(Internship).filter(
        Internship.status == ListingStatus.approved,
        Internship.source_active.is_(True),
        or_(Internship.source.is_(None), Internship.source != "seed"),
        _visible_freshness(),
        Internship.broken_link_reports < settings.broken_link_report_threshold,
    )
    if field:
        q = q.filter(Internship.field == field)
    if city:
        q = q.filter(Internship.city.contains(city))
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Internship.company.ilike(like), Internship.role.ilike(like), Internship.city.ilike(like)))
    if international_only:
        q = q.filter(Internship.accepts_international.is_(True))

    # Verification updates must not make old jobs appear newly published.
    rows = q.order_by(func.coalesce(Internship.published_at, Internship.first_seen_at, Internship.scraped_at).desc()).all()
    if sort == "least_competition":
        rows.sort(key=lambda r: (_size_rank(r.company_size), -((r.published_at or r.first_seen_at or r.scraped_at).timestamp() if (r.published_at or r.first_seen_at or r.scraped_at) else 0)))
    elif sort == "international":
        rows.sort(key=lambda r: (r.accepts_international is not True, -((r.published_at or r.first_seen_at or r.scraped_at).timestamp() if (r.published_at or r.first_seen_at or r.scraped_at) else 0)))

    favorited_ids: set[int] = set()
    if user:
        favorited_ids = {f.internship_id for f in db.query(Favorite).filter(Favorite.user_id == user.id).all()}
    sources = {s.source: s for s in db.query(DiscoverySource).all()}
    return [_to_out(r, favorited_ids, sources.get(r.source)) for r in rows]


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    rows = db.query(Internship).filter(
        Internship.status == ListingStatus.approved,
        Internship.source_active.is_(True),
        or_(Internship.source.is_(None), Internship.source != "seed"),
        _visible_freshness(),
        Internship.broken_link_reports < settings.broken_link_report_threshold,
    ).all()
    fields = sorted({r.field for r in rows})
    cities = sorted({r.city.split(" / ")[0].split(" (")[0] for r in rows})
    return {"total": len(rows), "fields": fields, "cities": cities}


@router.get("/discovery-status")
def discovery_status(db: Session = Depends(get_db)):
    sources = db.query(DiscoverySource).order_by(DiscoverySource.source).all()
    lease = db.get(DiscoveryLease, 1)
    now = datetime.now(timezone.utc)
    running = bool(lease and lease.lease_until.replace(tzinfo=timezone.utc) > now)
    return {
        "automatic": settings.enable_background_scraper,
        "refresh_interval_hours": settings.scrape_refresh_interval_hours,
        "freshness_window_days": settings.freshness_window_days,
        "running": running,
        "sources": [{"source": s.source, "status": s.status, "count": s.count,
                     "checked_at": s.checked_at, "last_success_at": s.last_success_at,
                     "message": s.message} for s in sources],
    }


@router.post("", response_model=InternshipOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
def submit_internship(request: Request, payload: InternshipCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    existing = db.query(Internship).filter(Internship.url == payload.url).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "A listing with this URL already exists")

    auto_approved = user.role == Role.admin or (
        user.role == Role.moderator and payload.field in user.moderated_field_list()
    )
    row = Internship(
        **payload.model_dump(),
        status=ListingStatus.approved if auto_approved else ListingStatus.pending,
        source=f"user:{user.id}", submitted_by_id=user.id,
        reviewed_by_id=user.id if auto_approved else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row, set())


@router.get("/pending", response_model=list[InternshipOut])
def list_pending(db: Session = Depends(get_db), user: User = Depends(require_role(Role.moderator, Role.admin))):
    q = db.query(Internship).filter(Internship.status == ListingStatus.pending)
    if user.role == Role.moderator:
        fields = user.moderated_field_list()
        if not fields:
            return []
        q = q.filter(Internship.field.in_(fields))
    rows = q.order_by(Internship.scraped_at.desc()).all()
    return [_to_out(r, set()) for r in rows]


@router.post("/{internship_id}/approve", response_model=InternshipOut)
def approve_internship(internship_id: int, request: Request, decision: ModerationDecision = ModerationDecision(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(Internship).filter(Internship.id == internship_id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    require_field_moderator(row.field)(request, user)
    row.scraped_at = datetime.now(timezone.utc)
    row.source_active = True
    row.status = ListingStatus.approved
    row.reviewed_by_id = user.id
    db.commit()
    db.refresh(row)
    return _to_out(row, set())


@router.post("/{internship_id}/reject", response_model=InternshipOut)
def reject_internship(internship_id: int, request: Request, decision: ModerationDecision = ModerationDecision(), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(Internship).filter(Internship.id == internship_id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    if user.role != Role.admin and not (user.role == Role.moderator and row.field in user.moderated_field_list()):
        log_permission_denied(request, user.id, f"not a moderator for field '{row.field}' (reject)")
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"You're not a moderator for the '{row.field}' field")
    row.status = ListingStatus.rejected
    row.reviewed_by_id = user.id
    db.commit()
    db.refresh(row)
    return _to_out(row, set())


@router.delete("/{internship_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_internship(internship_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(Internship).filter(Internship.id == internship_id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    if user.role != Role.admin and not (user.role == Role.moderator and row.field in user.moderated_field_list()):
        log_permission_denied(request, user.id, f"not a moderator for field '{row.field}' (delete)")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to delete this listing")
    db.delete(row)
    db.commit()


@router.post("/{internship_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def favorite(internship_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(Internship).filter(Internship.id == internship_id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    exists = db.query(Favorite).filter(Favorite.user_id == user.id, Favorite.internship_id == internship_id).first()
    if not exists:
        db.add(Favorite(user_id=user.id, internship_id=internship_id))
        db.commit()


@router.delete("/{internship_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def unfavorite(internship_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(Favorite).filter(Favorite.user_id == user.id, Favorite.internship_id == internship_id).delete()
    db.commit()


@router.get("/favorites/mine", response_model=list[InternshipOut])
def my_favorites(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Internship).join(Favorite, Favorite.internship_id == Internship.id).filter(Favorite.user_id == user.id).all()
    favorited_ids = {r.id for r in rows}
    sources = {s.source: s for s in db.query(DiscoverySource).all()}
    return [_to_out(r, favorited_ids, sources.get(r.source)) for r in rows]


@router.post("/{internship_id}/report-broken-link", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/hour")
def report_broken_link(internship_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Any signed-in user can flag a listing as broken/expired/wrong —
    this is the actual fix for a listing that was genuinely open when
    added but has since closed. Once a listing collects
    broken_link_report_threshold reports (config.py, default 3), it's
    automatically hidden from the public board in list_internships —
    no moderator action required for it to stop being shown, though
    moderators can still review and clear a false report (see
    clear_reports below) or delete the listing outright.
    """
    row = db.query(Internship).filter(Internship.id == internship_id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    row.broken_link_reports += 1
    row.last_reported_broken_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/reported", response_model=list[InternshipOut])
def list_reported(db: Session = Depends(get_db), user: User = Depends(require_role(Role.moderator, Role.admin))):
    """Listings with at least one broken-link report, for moderators
    to review — field-scoped the same way the pending queue is."""
    q = db.query(Internship).filter(Internship.broken_link_reports > 0)
    if user.role == Role.moderator:
        fields = user.moderated_field_list()
        if not fields:
            return []
        q = q.filter(Internship.field.in_(fields))
    rows = q.order_by(Internship.broken_link_reports.desc()).all()
    return [_to_out(r, set()) for r in rows]


@router.post("/{internship_id}/clear-reports", response_model=InternshipOut)
def clear_reports(internship_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """A moderator manually re-checked the link and it's fine after
    all (or the reports were mistaken/malicious) — resets the counter
    so the listing reappears on the public board."""
    row = db.query(Internship).filter(Internship.id == internship_id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    require_field_moderator(row.field)(request, user)
    row.broken_link_reports = 0
    row.last_reported_broken_at = None
    db.commit()
    db.refresh(row)
    return _to_out(row, set())
