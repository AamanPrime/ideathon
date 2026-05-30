from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Frontline Desk Voice Assistant (Gemini Edition)"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./frontline_desk.db"

    # --- JWT auth ---
    jwt_secret: str = "dev-secret-change-me-dev-secret-change-me"
    jwt_algo: str = "HS256"
    jwt_access_ttl_min: int = 720
    seed_admin_email: str = "admin@bank.local"
    seed_admin_password: str = "ChangeMe!123"
    seed_admin_name: str = "Branch Admin"

    # Gemini API - Primary AI Provider
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-exp"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Demo / resilience
    demo_mode: bool = False

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_effective(self) -> tuple[str, str, str]:
        """Return (api_key, base_url, model) for Gemini."""
        model = self.gemini_model
        if "live" in model or "audio" in model:
            model = "gemini-2.0-flash"
        return self.gemini_api_key, self.gemini_base_url, model


@lru_cache
def get_settings() -> Settings:
    return Settings()
