"""
Storage factory. Callers do:

    from app.storage import get_storage_provider
    storage = get_storage_provider()
    path = await storage.upload("videos/abc123.mp4", data)

Switching backends is a `STORAGE_BACKEND=` change in .env — nothing
else in the codebase references LocalStorageProvider/S3StorageProvider
directly.
"""
from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageProvider


@lru_cache
def get_storage_provider() -> StorageProvider:
    settings = get_settings()
    backend = settings.storage_backend.lower()

    if backend == "local":
        from app.storage.local import LocalStorageProvider

        return LocalStorageProvider(
            base_path=settings.storage_local_path,
            public_base_url=settings.storage_public_base_url,
        )

    if backend in ("s3", "r2"):
        from app.storage.s3 import S3StorageProvider

        if not settings.storage_bucket:
            raise ValueError("STORAGE_BUCKET must be set when STORAGE_BACKEND is 's3' or 'r2'")
        return S3StorageProvider(
            bucket=settings.storage_bucket,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
            region=settings.storage_region,
            endpoint_url=settings.storage_endpoint_url,  # R2 sets this; AWS S3 leaves it None
            public_base_url=settings.storage_public_base_url,
        )

    if backend in ("azure", "gcs"):
        # Deliberately not built yet — no current need (Google Drive is
        # the asset store today per the architecture doc). Adding one
        # is the same shape as s3.py: implement StorageProvider, wire
        # it in here. Left as a clear stub rather than silently missing.
        raise NotImplementedError(
            f"STORAGE_BACKEND='{backend}' is not implemented yet. "
            "Add app/storage/{azure,gcs}.py implementing StorageProvider, "
            "then wire it into get_storage_provider()."
        )

    raise ValueError(f"Unknown STORAGE_BACKEND: '{settings.storage_backend}'")
