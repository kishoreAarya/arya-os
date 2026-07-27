"""
Storage Provider interface.

Beginner note: every generated file (image, video, thumbnail, voice
track) is currently referenced by `storage_path` string columns across
models/media.py. This interface is what those paths get written and
read through, so switching from local disk to S3/R2/Azure/GCS later is
a config change (`STORAGE_BACKEND=r2` in .env) — not a rewrite of every
agent that saves a file.
"""
from abc import ABC, abstractmethod


class StorageProvider(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Writes `data` under `key`, returns the storage_path to save
        in the DB (backend-specific: a local path or an object key)."""
        raise NotImplementedError

    @abstractmethod
    async def download(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_url(self, key: str) -> str:
        """Best-effort playback/preview URL. For local storage this may
        just be a file:// path or an internal API route; for object
        storage it's a public or presigned URL."""
        raise NotImplementedError
