from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://connectsphere:connectsphere@localhost:5432/connectsphere"
    )
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
