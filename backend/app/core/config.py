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

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    app_name: str = "arya-os"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    backend_port: int = 8000

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://arya:change_me@localhost:5432/arya_os"
    )

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ------------------------------------------------------------------
    # LLM Provider API Keys
    # ------------------------------------------------------------------
    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ------------------------------------------------------------------
    # Media Provider API Keys
    # ------------------------------------------------------------------
    runpod_api_key: str | None = None
    fal_api_key: str | None = None
    replicate_api_key: str | None = None

    # ------------------------------------------------------------------
    # Provider Configuration
    # ------------------------------------------------------------------
    comfyui_base_url: str | None = None
    comfyui_timeout_seconds: int = 300

    runpod_endpoint_id: str | None = None
    runpod_timeout_seconds: int = 300

    fal_timeout_seconds: int = 300
    replicate_timeout_seconds: int = 300

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # ------------------------------------------------------------------
    # Global Tunables
    # ------------------------------------------------------------------
    quality_threshold: float = 70.0
    max_retry_attempts: int = 3
    api_timeout_seconds: int = 60
    image_resolution: str = "1024x1024"
    video_fps: int = 30
    max_cost_per_video_usd: float = 5.00
    default_llm_model: str = "deepseek/deepseek-chat"

    # ------------------------------------------------------------------
    # Feature Flags
    # ------------------------------------------------------------------
    enable_autonomous_publishing: bool = False
    enable_learning_loop: bool = True
    enable_experimental_thumbnail_agent: bool = False
    enable_new_image_model: bool = False
    enable_new_validator: bool = False
    enable_background_scheduler: bool = True

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    storage_backend: str = "local"
    storage_local_path: str = "./data/storage"
    storage_bucket: str | None = None
    storage_endpoint_url: str | None = None
    storage_region: str | None = None
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    storage_public_base_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings instance.
    """
    return Settings()