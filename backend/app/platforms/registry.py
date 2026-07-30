"""Platform adapter registry and factory.

Mirrors the AGENT_REGISTRY pattern (app/agents/registry.py):
- Plain dict mapping platform name -> adapter CLASS
- Lazy instantiation via factory function
- No auto-discovery — to add a platform, import it and add one line.

The factory (get_platform_adapter) is the ONLY way agents should
obtain an adapter. It handles:
- Registry lookup
- Instantiation with db + secrets
- Clear error if the platform isn't registered.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets import SecretsManager, get_secrets_manager
from app.platforms.base import PlatformAdapter
from app.platforms.youtube import YouTubeAdapter

PLATFORM_ADAPTER_REGISTRY: dict[str, type[PlatformAdapter]] = {
    "youtube": YouTubeAdapter,
    # To add a new platform:
    # 1. Create app/platforms/<platform>.py implementing PlatformAdapter
    # 2. Import it above
    # 3. Add "<platform>": <Platform>Adapter to this dict
}


class UnknownPlatformError(RuntimeError):
    """Raised when a platform name doesn't match anything in
    PLATFORM_ADAPTER_REGISTRY."""

    def __init__(self, platform: str):
        self.platform = platform
        super().__init__(
            f"Unknown platform '{platform}' — not in PLATFORM_ADAPTER_REGISTRY "
            f"(available: {sorted(PLATFORM_ADAPTER_REGISTRY.keys())})"
        )


def get_platform_adapter(
    platform: str,
    db: AsyncSession,
    secrets: SecretsManager | None = None,
) -> PlatformAdapter:
    """Factory: look up the adapter class for `platform`, instantiate
    it with the request-scoped db session and secrets manager.

    Usage in PublishingAgent:
        adapter = get_platform_adapter(platform, self._db)
    """
    adapter_cls = PLATFORM_ADAPTER_REGISTRY.get(platform)
    if adapter_cls is None:
        raise UnknownPlatformError(platform)

    secrets_manager = secrets or get_secrets_manager()
    return adapter_cls(db=db, secrets=secrets_manager)
