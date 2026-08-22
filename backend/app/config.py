"""Centralized application settings.

All configuration is read from environment variables (populated from `.env`
in local dev, and from the hosting platform's env panel in Render/Vercel).
Nothing in this module calls an LLM or a database — it only describes what
configuration exists and validates it's shaped correctly, so a missing or
malformed value fails fast at startup instead of surfacing as a confusing
error three layers deep during a real request.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings resolves a relative env_file against the process's CWD,
# not the repo root, and doesn't walk up parent directories. Our local-dev
# flow runs uvicorn from backend/ while .env lives at the repo root (README's
# `cp ../.env.example ../.env`), so a relative ".env" here silently missed it
# — every field has a "" default, so the miss was never an error, just a
# fully-unconfigured app that looked configured. Anchoring to this file's own
# location makes the lookup independent of whatever directory the process
# happens to be started from.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings, populated from environment variables.

    Field names match `.env.example` exactly (case-insensitive by default in
    pydantic-settings) so the two files stay easy to diff against each other.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM providers ---------------------------------------------------
    gemini_api_key: str = Field(default="", description="Primary provider key")
    gemini_model: str = Field(default="gemini-3.1-flash-lite")
    openrouter_api_key: str = Field(default="", description="Fallback provider key")
    openrouter_model: str = Field(default="")

    # --- Database / memory / trace log (Supabase) -------------------------
    supabase_url: str = Field(default="")
    supabase_secret_key: str = Field(default="")
    database_url: str = Field(default="")

    # --- App config --------------------------------------------------------
    environment: Literal["development", "production"] = Field(default="development")
    port: int = Field(default=8000)
    cors_origins: str = Field(default="http://localhost:5173")
    log_level: Literal["debug", "info", "warning", "error"] = Field(default="info")

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS as a comma-split, whitespace-trimmed list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def llm_providers_configured(self) -> bool:
        """True once at least the primary provider has a real key.

        Used by the health endpoint (Day 1) and, from Day 2 onward, by the
        agent graph to fail a session creation early with a clear error
        instead of a confusing downstream provider exception.
        """
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — env is read once per process.

    Tests override this via FastAPI's `dependency_overrides`, not by
    mutating environment variables mid-run.
    """
    return Settings()
