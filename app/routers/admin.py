from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import scraper as scraper_module
from ..database import get_db
from ..deps import require_role
from ..models import User, Role
from ..rate_limiter import limiter
from ..schemas import PromoteRequest, UserOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_role(Role.admin))):
    rows = db.query(User).order_by(User.email).all()
    return [UserOut(id=u.id, email=u.email, role=u.role, moderated_fields=u.moderated_field_list()) for u in rows]


@router.post("/users/{user_id}/role", response_model=UserOut)
def set_user_role(user_id: int, payload: PromoteRequest, db: Session = Depends(get_db), _: User = Depends(require_role(Role.admin))):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    target.role = payload.role
    target.moderated_fields = ",".join(payload.moderated_fields) if payload.role == Role.moderator else ""
    db.commit()
    db.refresh(target)
    return UserOut(id=target.id, email=target.email, role=target.role, moderated_fields=target.moderated_field_list())


@router.post("/scrape-refresh")
@limiter.limit("6/hour")
def scrape_refresh(request: Request, db: Session = Depends(get_db), _: User = Depends(require_role(Role.admin))):
    from ..discovery import refresh
    return refresh(manual=True)
