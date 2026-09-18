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

    @property
    def resolved_test_database_url(self) -> str:
        if self.test_database_url:
            return self.test_database_url
        base, _, name = self.database_url.rpartition("/")
        return f"{base}/{name}_test"


settings = Settings()
