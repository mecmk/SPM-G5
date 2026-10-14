from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://connectsphere:connectsphere@localhost:5433/connectsphere"
    )
    # Database used by the backend test-suite. It is dropped and recreated by
    # tests/conftest.py on every run, so it must NOT be the development database.
    # Defaults to "<database_url database name>_test" on the same server.
    test_database_url: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- session settings (story 1.1) ---
    session_cookie_name: str = "connectsphere_session"
    session_ttl_hours: int = 12
    # Set to True when serving over HTTPS. Left False for local HTTP development.
    session_cookie_secure: bool = False

    # --- sign-in lockout (story 1.1 AC6, bug f1.1.2) ---
    # This many failures for one e-mail within the window lock sign-in for that e-mail.
    login_max_failures: int = 5
    login_failure_window_minutes: int = 15
    login_lock_minutes: int = 15

    # --- uploaded pictures (story 2.1 AC14 for events, story 8.3 AC5 for venues) ---
    # Where event cover pictures (events/) and venue pictures (venues/) are written. Git-ignored;
    # tests point it at a temporary folder.
    upload_dir: Path = Path(__file__).resolve().parent.parent / "uploads"

    # --- tentative venue holds (story 12.7) ---
    # Venue Staff set each hold's expiry as they approve; the system has no default (Q45). The
    # event's coordinator is warned this many hours before a hold expires (AC2), assumed until the
    # customer gives a lead time (Q34).
    hold_expiry_reminder_hours: int = 24
    # How often the API expires lapsed holds and sends due warnings, in seconds; 0 turns the timer
    # off (the backend tests do, since its session would be the development database's).
    hold_sweep_interval_seconds: float = 60

    @property
    def resolved_test_database_url(self) -> str:
        if self.test_database_url:
            return self.test_database_url
        base, _, name = self.database_url.rpartition("/")
        return f"{base}/{name}_test"


settings = Settings()
