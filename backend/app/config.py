from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Frontline Desk Voice Assistant"
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

    # Bhashini / ULCA — https://bhashini.gitbook.io/bhashini-apis/
    bhashini_user_id: str = ""
    bhashini_ulca_api_key: str = ""
    bhashini_pipeline_config_url: str = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"

    # --- LLM (swappable: openai | groq | mock) ---
    llm_provider: str = "mock"

    # Groq (OpenAI-compatible)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # OpenAI-compatible
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    # Demo / resilience
    demo_mode: bool = False

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_effective(self) -> tuple[str, str, str]:
        """Return (api_key, base_url, model) for the active LLM provider, or empty key for mock."""
        p = (self.llm_provider or "mock").lower()
        if p == "groq":
            return self.groq_api_key, self.groq_base_url, self.groq_model
        if p == "openai":
            return self.llm_api_key, self.llm_base_url, self.llm_model
        return "", "", ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
