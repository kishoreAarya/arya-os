"""
Centralized application settings.

Design principle: no module reaches into os.environ directly.
Everything flows through this single Settings object, injected
wherever it's needed (dependency injection, not global state).
"""
from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute Hermes-Agent commit pin — single source of truth.
# HERMES_INTEGRATION_SPEC §2/§15: changing this requires source verification,
# runtime security verification, architecture review, and explicit approval.
HERMES_COMMIT_PIN = "c0d7294769a38c17ceae51d8f7995e66e1dcae27"
# Tree hash of the pinned Hermes commit — the second identity anchor,
# verified alongside the commit at the build boundary (app.hermes.source).
# Same §15 change control.
HERMES_TREE_PIN = "eff225d07a45bcff9ecd96d4632564657218798e"


def _reject_bool(value: object) -> object:
    # bool is a subclass of int, so pydantic's lax mode would silently coerce
    # True/False into 1/0 limits. Hermes limits reject bools instead: invalid
    # configuration fails, it is never coerced (HERMES_INTEGRATION_SPEC §12).
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid numeric Hermes setting")
    return value


HermesLimitInt = Annotated[int, BeforeValidator(_reject_bool)]
HermesLimitFloat = Annotated[float, BeforeValidator(_reject_bool)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # App & Server Configuration
    # ------------------------------------------------------------------
    app_name: str = "arya-os"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    uvicorn_workers: int = 1
    uvicorn_timeout_keep_alive: int = 65
    uvicorn_timeout_graceful_shutdown: int = 60
    auto_run_migrations: bool = True

    # ------------------------------------------------------------------
    # Security / API Authentication
    # ------------------------------------------------------------------
    arya_api_key: str | None = None
    api_auth_enabled: bool = True
    # Comma-separated allowlist of browser origins permitted by CORS.
    # No wildcards: the API uses Bearer headers, not cookies, so
    # allow_credentials stays False and only explicit origins are echoed.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://arya:change_me@localhost:5432/arya_os"
    )
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

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
    fal_key: str | None = None
    together_api_key: str | None = None
    replicate_api_key: str | None = None
    elevenlabs_api_key: str | None = None

    # ------------------------------------------------------------------
    # Provider Configuration
    # ------------------------------------------------------------------
    comfyui_base_url: str | None = None
    comfyui_timeout_seconds: int = 300

    runpod_endpoint_id: str | None = None
    runpod_timeout_seconds: int = 300

    fal_timeout_seconds: int = 300
    together_timeout_seconds: int = 300
    replicate_timeout_seconds: int = 300

    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_model_id: str = "eleven_turbo_v2_5"
    elevenlabs_timeout_seconds: int = 60
    elevenlabs_cost_per_1k_chars_usd: float = 0.30
    default_voice_provider: str = "elevenlabs"
    default_video_provider: str = "kling"
    kling_timeout_seconds: int = 360

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

    # Task 22: Cost x Quality Frontier Tunables
    visual_keyframe_candidates: int = 1
    max_kling_shots: int = 1
    visual_budget_usd: float = 0.80
    quality_floor: float = 8.5
    candidate_policy: str = "fixed"  # 'fixed' or 'smart'
    allocation_strategy: str = "hybrid"  # 'hybrid' or 'smart'

    # Task 24: Visual Standard V2 Integration Tunables
    visual_profile: str = "current_legacy"  # 'current_legacy', 'visual_v2_lean', 'visual_v2_flagship'
    visual_dry_run: bool = False

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

    # ------------------------------------------------------------------
    # YouTube / Platform Settings
    # ------------------------------------------------------------------
    youtube_api_key: str | None = None
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    youtube_refresh_token: str | None = None
    youtube_channel_id: str | None = None

    # ------------------------------------------------------------------
    # Reddit Research Settings
    # ------------------------------------------------------------------
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "AryaOS-Research/1.0 (Content Factory Assistant)"
    reddit_timeout_seconds: float = 10.0

    # ------------------------------------------------------------------
    # Postiz Publishing Settings
    # ------------------------------------------------------------------
    postiz_base_url: str = "http://localhost:4007"
    postiz_api_key: str | None = None
    postiz_timeout_seconds: float = 30.0
    postiz_default_integration_id: str | None = None

    # ------------------------------------------------------------------
    # Hermes Runtime (V2) — see docs/architecture/HERMES_INTEGRATION_SPEC.md
    #
    # Disabled by default. There are deliberately NO default values for the
    # resource limits: enabling Hermes requires the operator to supply every
    # value, and app.hermes.config.get_validated_hermes_config() fails closed
    # on any missing, non-finite, or non-positive limit. Unbounded is not a
    # valid configuration.
    # ------------------------------------------------------------------
    hermes_enabled: bool = False
    hermes_commit_pin: str = HERMES_COMMIT_PIN
    hermes_plugin_path: str | None = None
    hermes_home: str | None = None
    hermes_max_iterations: HermesLimitInt | None = None
    hermes_max_execution_seconds: HermesLimitFloat | None = None
    hermes_max_tool_calls: HermesLimitInt | None = None
    hermes_max_tool_calls_per_capability: HermesLimitInt | None = None
    hermes_max_generation_budget_usd: HermesLimitFloat | None = None
    hermes_max_context_tokens: HermesLimitInt | None = None
    hermes_max_blocked_requests: HermesLimitInt | None = None



@lru_cache
def get_settings() -> Settings:
    """
    Cached settings instance.
    """
    return Settings()