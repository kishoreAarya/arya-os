"""
Centralized application settings.

Design principle: no module reaches into os.environ directly.
Everything flows through this single Settings object, injected
wherever it's needed (dependency injection, not global state).
"""
from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
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
    # Security / API Authentication & CORS
    # ------------------------------------------------------------------
    arya_api_key: str | None = None
    api_auth_enabled: bool = True
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:4173",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:4173",
            "http://127.0.0.1:8000",
        ]
    )
    cors_allow_credentials: bool = True

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except Exception:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

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
    fal_api_key: str | None = Field(default=None, repr=False)
    fal_key: str | None = Field(default=None, repr=False)
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

    # Creator Mode Concurrency & Cache Retention
    creator_max_concurrent_jobs: int = 5
    creator_active_jobs_retention_limit: int = 100

    # Workflow Execution Lease & Stale Run Recovery
    workflow_lease_timeout_seconds: int = 300
    workflow_heartbeat_interval_seconds: int = 15
    enable_workflow_auto_recovery: bool = False

    # ------------------------------------------------------------------
    # Feature Flags & Stage 25 Live Execution Gates
    # ------------------------------------------------------------------
    enable_autonomous_publishing: bool = False
    enable_learning_loop: bool = True
    enable_experimental_thumbnail_agent: bool = False
    enable_new_image_model: bool = False
    enable_new_validator: bool = False
    enable_background_scheduler: bool = True
    enable_live_provider_execution: bool = Field(
        default=False,
        description="Gate controlling live provider execution in Stage 25. Defaults to False (fail-closed).",
    )
    enable_live_local_execution: bool = Field(
        default=False,
        description="Gate controlling local media tool execution (e.g. camera push / FFmpeg). Defaults to False (fail-closed).",
    )

    @field_validator("enable_live_provider_execution", mode="before")
    @classmethod
    def _validate_enable_live_provider_execution(cls, v: object) -> bool:
        """Fail-closed validation for live provider execution gate.
        Only strictly recognized affirmative boolean representations can enable it;
        all invalid, missing, unparseable, or unrecognized values fail closed to False.
        """
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in ("true", "1", "yes", "on"):
                return True
            # Any invalid, empty, or unrecognized string strictly fails closed to False
            return False
        if isinstance(v, (int, float)):
            return bool(v == 1)
        return False

    @field_validator("enable_live_local_execution", mode="before")
    @classmethod
    def _validate_enable_live_local_execution(cls, v: object) -> bool:
        """Fail-closed validation for live local execution gate.
        Only strictly recognized affirmative boolean representations can enable it;
        all invalid, missing, unparseable, or unrecognized values fail closed to False.
        """
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in ("true", "1", "yes", "on"):
                return True
            # Any invalid, empty, or unrecognized string strictly fails closed to False
            return False
        if isinstance(v, (int, float)):
            return bool(v == 1)
        return False

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
    # Artifact Retention & Lifecycle (MED-04)
    # ------------------------------------------------------------------
    artifact_retention_enabled: bool = Field(
        default=False,
        description="Explicit gate for actual deletion during artifact retention sweeps. Defaults to False (fail-closed/dry-run).",
    )
    artifact_retention_dry_run: bool = Field(
        default=True,
        description="Whether artifact retention sweeps run in dry-run mode (no files unlinked). Defaults to True.",
    )
    artifact_retention_days: int = Field(
        default=14,
        description="Threshold age in days before unreferenced scratch artifacts become eligible for pruning.",
    )
    artifact_retention_batch_size: int = Field(
        default=100,
        description="Maximum number of candidate files to evaluate/prune per maintenance sweep.",
    )

    # ------------------------------------------------------------------
    # Lease Expiry & Background Recovery (Phase 3.2.4.4.6.3.3.14)
    # ------------------------------------------------------------------
    enable_lease_expiry_sweeper: bool = Field(
        default=True,
        description="Whether background sweeper for expired action leases is enabled.",
    )
    lease_expiry_sweep_interval_seconds: int = Field(
        default=30,
        description="Sweep interval in seconds for expired action lease detection.",
    )
    lease_expiry_batch_size: int = Field(
        default=50,
        description="Maximum number of candidate executing actions to evaluate/recover per sweep.",
    )
    lease_heartbeat_interval_seconds: int = Field(
        default=30,
        description="Interval in seconds for active worker lease renewal heartbeats.",
    )

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

    def validate_production_safety(self) -> None:
        """Validate production configuration to prevent insecure deployments.

        Raises:
            ValueError: If insecure or default development settings are detected in production.
        """
        if (self.app_env or "").lower() != "production":
            return

        errors: list[str] = []

        insecure_keys = {
            "arya_dev_secret_key_change_in_production",
            "change_me",
            "secret",
            "password",
            "admin",
        }
        if not self.arya_api_key or not self.arya_api_key.strip():
            errors.append("ARYA_API_KEY must be set in production.")
        elif self.arya_api_key.strip() in insecure_keys:
            errors.append("ARYA_API_KEY is set to an insecure default placeholder.")
        elif len(self.arya_api_key.strip()) < 16:
            errors.append("ARYA_API_KEY must be at least 16 characters in production.")

        origins = [o.strip() for o in self.cors_allowed_origins if o.strip()]
        if "*" in origins and self.cors_allow_credentials:
            errors.append("CORS cannot allow credentials with wildcard origin ('*') in production.")

        if "change_me" in (self.database_url or ""):
            errors.append("DATABASE_URL contains default insecure placeholder credentials ('change_me').")

        if self.enable_live_provider_execution:
            errors.append(
                "ENABLE_LIVE_PROVIDER_EXECUTION must remain False in production until Stage 25 Phase 3.2.4 authorization."
            )

        if errors:
            raise ValueError(
                "Production configuration validation failed:\n - " + "\n - ".join(errors)
            )


def validate_production_settings(settings: Settings | None = None) -> None:
    """Validate settings for production deployment safety."""
    if settings is None:
        settings = get_settings()
    settings.validate_production_safety()


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings instance.
    """
    return Settings()