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

import posixpath


def lexical_canonical_key(key: str) -> str:
    """Lexical key normalization: collapse `.` components and repeated
    separators without touching anything else. Used as the fallback for
    references that do not resolve inside a storage root (ratified F-01
    contract: preserve the existing out-of-root workflow — no new
    rejection policy). Key-oriented backends treat keys as opaque, so
    backslashes and case are preserved."""
    return posixpath.normpath(key)


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

    def canonical_key(self, key: str) -> str:
        """Canonical identity form of a storage reference (F-01).

        The default is lexical key normalization — correct for
        key-oriented backends (S3/R2 object keys are opaque strings:
        case-sensitive, backslash-preserving). Path-resolving backends
        (local disk) override with storage-root resolution so that
        alias spellings of the same physical asset collapse to one key.
        URLs are NOT handled here (router policy keeps raw URL strings
        as their own identity namespace)."""
        return lexical_canonical_key(key)
