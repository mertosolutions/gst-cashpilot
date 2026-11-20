"""Application settings. Everything environment specific lives here (nothing is hard coded elsewhere)."""
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    app_name: str = "GST CashPilot API"
    api_prefix: str = "/api/v1"

    # Data: SQLite for local work, AlloyDB (PostgreSQL) in Google Cloud
    database_url: str = f"sqlite:///{BASE_DIR / 'cashpilot.db'}"
    upload_dir: str = str(BASE_DIR / "uploads")
    auto_seed: bool = True

    # Auth: "dev" trusts the X-Demo-User header, "firebase" verifies Firebase ID tokens
    auth_mode: str = "dev"
    firebase_project_id: str | None = None
    demo_owner_uid: str = "demo-owner"

    # Google AI (all optional: the app works offline with local engines)
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY")
    )
    gemini_model: str = "gemini-3.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    # read PDFs that have a clean text layer locally (instant, no Gemini quota). Photos always go to Gemini.
    ocr_prefer_local_for_text_pdf: bool = True

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Business rules
    amount_tolerance: float = 1.0  # rupees: amounts within this are treated as equal
    return_due_day: int = 20  # GSTR-3B due day in the month after the tax period

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
