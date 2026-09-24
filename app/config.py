"""
Centralised configuration, loaded from environment variables (and a
.env file in development). Nothing secret lives in code — see
.env.example for what to set.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Auth
    secret_key: str = "dev-only-secret-change-me"  # nosemgrep: hardcoded-secret-assignment — this is the placeholder the app is specifically designed to detect and refuse to boot on in production (see main.py), not a real credential
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # Database — sqlite for local dev, swap DATABASE_URL to a Postgres
    # URL in production (see README / docker-compose.yml)
    database_url: str = "sqlite:///./internships.db"

    # CORS — comma-separated list of origins allowed to call the API.
    # Never use "*" once real user accounts/cookies are involved.
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # "development" or "production" — flips on stricter security
    # headers (HSTS) and disables interactive API docs.
    environment: str = "development"

    # Optional — creates a first admin account on startup if no admin
    # exists yet in the database. Leave unset after first deploy.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # AI resume tailoring — requires an Anthropic API key. Feature is
    # simply unavailable (endpoints return a clear error) if unset.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"

    # Account lockout (separate from the per-IP rate limit on /login)
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Refresh token cookie
    refresh_cookie_name: str = "refresh_token"
    max_request_body_bytes: int = 1_000_000  # 1 MB — plenty for a pasted resume, not for an abusive payload

    # The public board only ever shows listings added/last-verified
    # within this many days — anything older is filtered out of
    # search entirely, not just flagged. Configurable because it's a
    # real product tradeoff: without something (a scheduled scrape,
    # or moderators periodically re-approving) touching every
    # listing's scraped_at at least this often, the board empties out
    # on its own. See README.
    freshness_window_days: int = 7

    # A listing hidden from the public board once this many distinct
    # "report broken link" clicks land on it — see
    # routers/internships.py's report_broken_link and the board query
    # in list_internships. Catches a listing that closes AFTER it was
    # added, which the freshness window alone can't.
    broken_link_report_threshold: int = 3

    # Automatic periodic scraping — the app searching on its own,
    # rather than waiting for an admin to click "scrape refresh".
    # Enabled by default: this hits real external APIs
    # (boards-api.greenhouse.io, api.lever.co, jobs.csiro.au) on a
    # schedule and writes to the database unattended, with a shared database lease to avoid duplicate refreshes. See main.py's _scheduler_loop.
    enable_background_scraper: bool = True
    scrape_refresh_interval_hours: int = Field(default=6, ge=1, le=168)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def cookie_secure(self) -> bool:
        # Secure cookies require HTTPS. In production (real deployment,
        # real TLS) this is True; kept False in dev so the refresh
        # cookie still works over plain http://127.0.0.1 while testing.
        return self.environment == "production"


settings = Settings()
