"""
Feature flag lookups.

Usage anywhere in the codebase:

    from app.services.feature_flags import is_enabled
    if await is_enabled("enable_autonomous_publishing"):
        ...

Precedence: a FeatureFlag row in the DB (if one exists for that name)
wins; otherwise falls back to the matching boolean on Settings. This
means: ship with safe defaults in .env, flip individual flags at
runtime from the dashboard without touching code or redeploying.
"""
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.models.feature_flag import FeatureFlag

_CACHE_TTL_SECONDS = 30
_cache: dict[str, tuple[bool, float]] = {}


async def is_enabled(name: str) -> bool:
    cached = _cache.get(name)
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FeatureFlag).where(FeatureFlag.name == name))
        flag = result.scalar_one_or_none()

    if flag is not None:
        value = flag.enabled
    else:
        value = bool(getattr(get_settings(), name, False))

    _cache[name] = (value, time.monotonic())
    return value


async def set_flag(name: str, enabled: bool, description: str | None = None) -> FeatureFlag:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FeatureFlag).where(FeatureFlag.name == name))
        flag = result.scalar_one_or_none()
        if flag is None:
            flag = FeatureFlag(name=name, enabled=enabled, description=description)
            session.add(flag)
        else:
            flag.enabled = enabled
            if description is not None:
                flag.description = description
        await session.commit()
        await session.refresh(flag)

    _cache.pop(name, None)
    return flag


async def list_flags() -> list[FeatureFlag]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FeatureFlag))
        return list(result.scalars().all())
