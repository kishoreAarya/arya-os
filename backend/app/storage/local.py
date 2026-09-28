"""Local disk storage — the default backend, no external deps."""
import asyncio
import posixpath
from pathlib import Path

from app.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_path: str, public_base_url: str | None = None):
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url

    def _resolve(self, key: str) -> Path:
        if not key or not isinstance(key, str):
            raise ValueError("Storage key must be a non-empty string")
        if "\0" in key:
            raise ValueError(f"Invalid key containing null byte: {key}")

        storage_root = self.base_path.resolve()
        normalized_key = key.replace("\\", "/")

        if normalized_key.startswith("/"):
            target = Path(normalized_key).resolve()
            if storage_root not in target.parents and target != storage_root:
                raise ValueError(f"Refusing to access outside storage root: {key}")
            return target

        clean_key = normalized_key.lstrip("/")
        path = (self.base_path / clean_key).resolve()
        if storage_root not in path.parents and path != storage_root:
            raise ValueError(f"Refusing to access outside storage root: {key}")
        return path

    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._resolve(key)
        storage_root = self.base_path.resolve()
        if path == storage_root:
            raise ValueError("Cannot upload to storage root directory itself")
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return str(path.relative_to(self.base_path))

    async def download(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(f"Storage asset not found or not a regular file: {key}")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        try:
            path = self._resolve(key)
            if path.is_file():
                await asyncio.to_thread(path.unlink)
        except (ValueError, FileNotFoundError):
            pass

    async def exists(self, key: str) -> bool:
        try:
            path = self._resolve(key)
            return path.is_file()
        except (ValueError, OSError):
            return False

    def get_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key.lstrip('/')}"
        return str(self._resolve(key))

    def canonical_key(self, key: str) -> str:
        """Storage-root-resolved canonical key (ratified F-01 contract).

        Resolves through the provider's own semantics — backslash
        normalization, symlink following, and root containment on the
        RESOLVED target — and expresses the result relative to the
        storage root, so alias spellings of the same physical in-root
        asset (`./`, `.` components, repeated separators, equivalent
        absolute paths, in-root symlinks) collapse to one key. Case is
        preserved and no Unicode normalization is applied (the key
        namespace is case-sensitive and byte-preserving).

        References that do not resolve inside the storage root (external
        absolute/local files, escaping symlinks) fall back to lexical
        normalization — the existing out-of-root workflow is preserved,
        and no new rejection policy is introduced here. Escaping
        symlinks therefore keep their OWN spelling's identity, never the
        out-of-root target's."""
        if not isinstance(key, str) or not key or "\0" in key:
            return posixpath.normpath((key or "").replace("\\", "/"))
        try:
            resolved = self._resolve(key)
            return str(resolved.relative_to(self.base_path))
        except (ValueError, OSError):
            # Out-of-root or unresolvable: lexical fallback (the router's
            # `..`/null-byte rejection has already run for API input).
            return posixpath.normpath(key.replace("\\", "/"))
