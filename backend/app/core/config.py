"""
Centralized application settings.

Design principle: no module reaches into os.environ directly.
Everything flows through this single Settings object, injected
wherever it's needed (dependency injection, not global state).
"""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "arya-os"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    backend_port: int = 8000

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://arya:change_me@localhost:5432/arya_os"
    )

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- Providers (all optional at this stage; Sprint 3 wires these in) ---
    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    runpod_api_key: str | None = None
    fal_api_key: str | None = None
    replicate_api_key: str | None = None

    # --- Notifications ---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- Global tunables (Hardening Pass #3) ---
    # Anything an agent, validator, or provider call would otherwise
    # hardcode lives here instead, so tuning the pipeline is a .env
    # change, not a code change.
    quality_threshold: float = 70.0          # min quality_score to pass validation
    max_retry_attempts: int = 3              # per artifact, before escalating to human
    api_timeout_seconds: int = 60
    image_resolution: str = "1024x1024"
    video_fps: int = 30
    max_cost_per_video_usd: float = 5.00     # circuit breaker — see ProviderRouter
    default_llm_model: str = "deepseek/deepseek-chat"

    # --- Feature flags (env-level defaults; DB-backed overrides win —
    # see app/services/feature_flags.py) ---
    enable_autonomous_publishing: bool = False
    enable_learning_loop: bool = True
    enable_experimental_thumbnail_agent: bool = False
    enable_new_image_model: bool = False
    enable_new_validator: bool = False
    enable_background_scheduler: bool = True

    # --- Storage ---
    storage_backend: str = "local"  # "local" | "s3" | "r2" | "azure" | "gcs"
    storage_local_path: str = "./data/storage"
    storage_bucket: str | None = None
    storage_endpoint_url: str | None = None  # for R2 / non-AWS S3-compatible
    storage_region: str | None = None
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    storage_public_base_url: str | None = None  # for building playback/preview URLs


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — read once, reused everywhere via DI."""
    return Settings()
