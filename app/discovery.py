"""Shared refresh service with a database lease across API workers."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .database import SessionLocal
from .models import DiscoveryLease
from .config import settings
from . import scraper


def refresh(manual=False):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if db.get(DiscoveryLease, 1) is None:
            db.add(DiscoveryLease(id=1, lease_until=now, next_run_at=now))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # Another worker initialized the singleton first.
        query = update(DiscoveryLease).where(DiscoveryLease.id == 1, DiscoveryLease.lease_until <= now)
        if not manual:
            query = query.where(DiscoveryLease.next_run_at <= now)
        # Longer than the bounded source request budget; crashes release by expiry.
        acquired = db.execute(query.values(lease_until=now + timedelta(hours=1))).rowcount
        db.commit()
        if not acquired:
            return {'scraped': 0, 'added': 0, 'updated': 0, 'busy': True}
    try:
        rows = scraper.run_all_scrapers()
        with SessionLocal() as db:
            added, updated = scraper.apply_scrape_results(db, rows)
            lease = db.get(DiscoveryLease, 1)
            lease.lease_until = datetime.now(timezone.utc)
            reports = getattr(rows, 'reports', {})
            all_failed = bool(reports) and all(r['status'] == 'error' for r in reports.values())
            lease.next_run_at = lease.lease_until + (timedelta(minutes=5) if all_failed else timedelta(hours=settings.scrape_refresh_interval_hours))
            db.commit()
        return {'scraped': len(rows), 'added': added, 'updated': updated}
    except Exception:
        with SessionLocal() as db:
            lease = db.get(DiscoveryLease, 1)
            lease.lease_until = datetime.now(timezone.utc)
            lease.next_run_at = lease.lease_until + timedelta(minutes=5)
            db.commit()
        raise
